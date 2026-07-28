"""Clock and error-boundary regressions for legacy market reads."""

import pytest

from ladder_dragon.execution import tools_market


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
