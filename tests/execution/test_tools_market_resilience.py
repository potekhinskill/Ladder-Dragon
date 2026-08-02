"""Clock and error-boundary regressions for legacy market reads."""

import pytest

from ladder_dragon.execution import tools_market


@pytest.fixture(autouse=True)
def reset_tools_market_rate_limit(monkeypatch):
    """Isolate the process-local cooldown between transport tests."""
    monkeypatch.setattr(tools_market, "_rate_limit_until", 0.0)
    monkeypatch.setattr(tools_market, "_rate_limit_error", None)


def test_http_418_arms_retry_after_cooldown_without_network_retry(monkeypatch):
    calls = []
    sleeps = []

    class Response:
        status_code = 418
        headers = {"Retry-After": "600"}

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
            return Response()

    monkeypatch.setattr(tools_market, "SESSION", Session())
    monkeypatch.setattr(tools_market.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(tools_market.time, "sleep", sleeps.append)
    url = "https://api.binance.com/api/v3/time?signature=secret"

    with pytest.raises(tools_market.BinanceHttpError) as first:
        tools_market._do_request("GET", url)
    with pytest.raises(tools_market.BinanceHttpError) as second:
        tools_market._do_request("GET", url)

    assert first.value.status == 418
    assert first.value.retry_after_seconds == 600
    assert second.value is first.value
    assert len(calls) == 1
    assert sleeps == []
    assert "signature" not in str(first.value)
    assert "secret" not in str(first.value)


def test_http_429_invalid_retry_after_uses_bounded_default(monkeypatch):
    class Response:
        status_code = 429
        headers = {"Retry-After": "invalid"}

    monkeypatch.setattr(
        tools_market.SESSION,
        "request",
        lambda *args, **kwargs: Response(),
    )
    monkeypatch.setattr(tools_market.time, "monotonic", lambda: 10.0)

    with pytest.raises(tools_market.BinanceHttpError) as caught:
        tools_market._do_request("GET", "https://api.binance.com/api/v3/time")

    assert caught.value.status == 429
    assert caught.value.retry_after_seconds == 1


def test_shorter_parallel_rate_limit_cannot_reduce_active_ban(monkeypatch):
    class Response:
        def __init__(self, status_code, retry_after):
            self.status_code = status_code
            self.headers = {"Retry-After": retry_after}

    monkeypatch.setattr(tools_market.time, "monotonic", lambda: 100.0)

    ban = tools_market._activate_rate_limit(
        Response(418, "600"), "https://api.binance.com/api/v3/time"
    )
    limited = tools_market._activate_rate_limit(
        Response(429, "1"), "https://api.binance.com/api/v3/depth"
    )

    assert limited is ban
    assert tools_market._rate_limit_until == 700.0
    assert tools_market._rate_limit_error is ban


def test_expired_market_read_cooldown_allows_one_new_request(monkeypatch):
    calls = []
    clock = iter((0.0, 0.0, 11.0))

    class Response:
        def __init__(self, status_code, retry_after=None):
            self.status_code = status_code
            self.headers = (
                {"Retry-After": retry_after} if retry_after is not None else {}
            )

    responses = iter((Response(429, "10"), Response(200)))

    def request(method, url, **kwargs):
        calls.append((method, url))
        return next(responses)

    monkeypatch.setattr(tools_market.SESSION, "request", request)
    monkeypatch.setattr(tools_market.time, "monotonic", lambda: next(clock))

    with pytest.raises(tools_market.BinanceHttpError):
        tools_market._do_request("GET", "https://api.binance.com/api/v3/time")
    accepted = tools_market._do_request(
        "GET", "https://api.binance.com/api/v3/time"
    )

    assert accepted.status_code == 200
    assert len(calls) == 2


def test_tools_market_clock_sync_uses_request_midpoint(monkeypatch):
    timestamps = iter((1_000.0, 1_000.2, 1_000.3))

    class Response:
        status_code = 200
        url = "https://api.binance.com/api/v3/time"

        @staticmethod
        def json():
            return {"serverTime": 1_000_100}

    monkeypatch.setattr(tools_market.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(
        tools_market,
        "_do_request",
        lambda *_args, **_kwargs: Response(),
    )

    tools_market._refresh_time_offset()

    assert tools_market._time_offset_ms == 0


def test_tools_market_signed_read_resyncs_once_after_minus_1021(monkeypatch):
    order_calls = []
    refreshed = []
    timestamps = iter((1_700_000_000_000, 1_700_000_005_000))

    class Rejected:
        status_code = 400
        url = "https://api.binance.com/api/v3/account"

        @staticmethod
        def json():
            return {
                "code": -1021,
                "msg": "Timestamp for this request is outside recvWindow.",
            }

    class Accepted:
        status_code = 200
        url = "https://api.binance.com/api/v3/account"

        @staticmethod
        def json():
            return {"canTrade": True}

    responses = iter((Rejected(), Accepted()))

    def request(*_args, **kwargs):
        order_calls.append(kwargs["params"])
        return next(responses)

    monkeypatch.setattr(tools_market, "API_KEY", "public")
    monkeypatch.setattr(tools_market, "API_SECRET", "private")
    monkeypatch.setattr(
        tools_market, "_timestamp_ms", lambda: next(timestamps)
    )
    monkeypatch.setattr(
        tools_market,
        "_refresh_time_offset",
        lambda: refreshed.append(True),
    )
    monkeypatch.setattr(tools_market, "_do_request", request)

    assert tools_market._signed_get("/api/v3/account") == {"canTrade": True}
    assert refreshed == [True]
    assert len(order_calls) == 2
    assert dict(order_calls[0])["timestamp"] == "1700000000000"
    assert dict(order_calls[1])["timestamp"] == "1700000005000"
    assert dict(order_calls[0])["signature"] != dict(order_calls[1])["signature"]


def test_tools_market_error_never_retains_signed_url(monkeypatch):
    alerts = []

    class Rejected:
        status_code = 401
        url = (
            "https://api.binance.com/api/v3/account?"
            "timestamp=1&signature=secret-signature"
        )

        @staticmethod
        def json():
            return {"code": -2015, "msg": "Invalid API key"}

    monkeypatch.setattr(
        tools_market,
        "notify_binance_auth_error",
        lambda **payload: alerts.append(payload),
    )

    with pytest.raises(tools_market.BinanceHttpError) as caught:
        tools_market._raise_for_binance(Rejected())

    assert caught.value.status == 401
    assert caught.value.code == -2015
    assert "signature" not in str(caught.value)
    assert "secret-signature" not in str(caught.value)
    assert alerts[0]["endpoint"] == "/api/v3/account"
