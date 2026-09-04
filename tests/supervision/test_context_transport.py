import json
import time

import pytest
import requests

from ladder_dragon.supervision.context_transport import HistoricalContextClient, MAX_RESPONSE_BYTES
from ladder_dragon.supervision.panic_observer import refresh_panic_observation


class Response:
    def __init__(self, payload=None, chunks=None, status=200):
        self.status_code, self.headers = status, {"Retry-After": "120"}
        self.chunks = chunks if chunks is not None else [json.dumps(payload).encode()]
        self.closed, self.read = False, 0

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            self.read += 1
            yield chunk

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make(session):
    return HistoricalContextClient(base_url="https://api.binance.com",
                                   credentials=lambda: ("test-key", "test-secret"), session=session)


def test_only_get_endpoints_and_bounded_clock_before_signing():
    responses = [Response({"symbols": []}), Response({"serverTime": time.time_ns() // 1_000_000}), Response({"symbol": "SOLUSDT"})]
    session = Session(responses)
    client = make(session)
    client.public_get("/api/v3/exchangeInfo", {"symbol": "SOLUSDT"})
    assert client.signed_get("/api/v3/account/commission", {"symbol": "SOLUSDT"}) == {"symbol": "SOLUSDT"}
    assert all(row.closed for row in responses)
    assert all(kwargs["stream"] and not kwargs["allow_redirects"] for _, kwargs in session.calls)
    assert session.calls[0][1]["headers"] == {}
    assert "signature" in session.calls[-1][1]["params"]
    for call in (client.signed_get, client.public_get):
        with pytest.raises(ValueError, match="unsupported"):
            call("/api/v3/order", {"symbol": "SOLUSDT"})
    assert len(session.calls) == 3


def test_public_kline_transport_feeds_halt_safe_panic_observer(tmp_path):
    bars = [
        [index * 60_000, "100", "101", "99", "100", "1", index * 60_000 + 59_999]
        for index in range(120)
    ]
    response = Response(bars)
    session = Session([response])
    client = HistoricalContextClient(
        base_url="https://api.binance.com",
        credentials=lambda: pytest.fail("public PANIC read accessed credentials"),
        session=session,
    )

    result = refresh_panic_observation(
        "SOLUSDT",
        public_get=client.public_get,
        now_ms=7_141_000,
        run_dir=tmp_path,
    )

    assert result["symbol"] == "SOLUSDT"
    assert response.closed
    assert session.calls[0][0].endswith("/api/v3/klines")
    assert session.calls[0][1]["params"] == {
        "symbol": "SOLUSDT",
        "interval": "1m",
        "limit": 120,
    }
    assert session.calls[0][1]["headers"] == {}


@pytest.mark.parametrize(
    ("params", "payload"),
    [
        ({"symbol": "SOLUSDT", "interval": "5m", "limit": 120}, []),
        ({"symbol": "SOLUSDT", "interval": "1m", "limit": 121}, []),
        ({"symbol": "solusdt", "interval": "1m", "limit": 120}, []),
        ({"symbol": "SOLUSDT", "interval": "1m", "limit": 120}, {}),
    ],
)
def test_public_kline_transport_rejects_contract_drift(params, payload):
    session = Session([Response(payload)])
    with pytest.raises(ValueError, match="unsupported|array"):
        make(session).public_get("/api/v3/klines", params)


def test_decoded_byte_limit_stops_before_json_and_closes_response():
    response = Response(chunks=[b"x" * 8192] * (MAX_RESPONSE_BYTES // 8192 + 5))
    with pytest.raises(ValueError, match="limit"):
        make(Session([response])).public_get("/api/v3/exchangeInfo", {"symbol": "SOLUSDT"})
    assert response.closed and response.read == MAX_RESPONSE_BYTES // 8192 + 1


@pytest.mark.parametrize("status", [302, 418, 429, 500])
def test_errors_never_read_provider_body_and_rate_limit_defers_next_read(status):
    response = Response(chunks=[b"sensitive-provider-text"], status=status)
    session = Session([response])
    client = make(session)
    with pytest.raises(RuntimeError, match="HTTP failure") as caught:
        client.public_get("/api/v3/exchangeInfo", {"symbol": "SOLUSDT"})
    assert response.closed and response.read == 0
    assert "sensitive-provider-text" not in str(caught.value)
    if status in (418, 429):
        with pytest.raises(RuntimeError, match="cooldown"):
            client.public_get("/api/v3/exchangeInfo", {"symbol": "SOLUSDT"})
        assert len(session.calls) == 1


def test_signed_cooldown_does_not_block_public_panic_observation():
    now_ms = time.time_ns() // 1_000_000
    bars = [
        [index * 60_000, "100", "101", "99", "100", "1", index * 60_000 + 59_999]
        for index in range(120)
    ]
    session = Session([
        Response({"serverTime": now_ms}),
        Response(status=429),
        Response(bars),
    ])
    client = make(session)

    with pytest.raises(RuntimeError, match="HTTP failure"):
        client.signed_get("/api/v3/account/commission", {"symbol": "SOLUSDT"})

    assert client.public_get(
        "/api/v3/klines",
        {"symbol": "SOLUSDT", "interval": "1m", "limit": 120},
    ) == bars
    assert len(session.calls) == 3


def test_public_cooldown_blocks_signed_reads_without_another_request():
    session = Session([Response(status=429)])
    client = make(session)

    with pytest.raises(RuntimeError, match="HTTP failure"):
        client.public_get("/api/v3/exchangeInfo", {"symbol": "SOLUSDT"})
    with pytest.raises(RuntimeError, match="cooldown"):
        client.signed_get(
            "/api/v3/account/commission", {"symbol": "SOLUSDT"}
        )

    assert len(session.calls) == 1


def test_network_failure_omits_signed_url_and_bad_clock_never_sends_signed_read():
    session = Session([requests.RequestException("signature=private-sentinel")])
    with pytest.raises(RuntimeError) as caught:
        make(session).signed_get("/api/v3/account/commission", {"symbol": "SOLUSDT"})
    assert "private-sentinel" not in str(caught.value)
    session = Session([Response({"serverTime": "bad-clock"})])
    with pytest.raises(ValueError, match="clock"):
        make(session).signed_get("/api/v3/account/commission", {"symbol": "SOLUSDT"})
    assert len(session.calls) == 1


@pytest.mark.parametrize("url", ["http://api.binance.com", "https://other.example", "https://api.binance.com/private",
                                "https://testnet.binance.vision"])
def test_untrusted_hosts_rejected_before_credentials(url):
    with pytest.raises(ValueError, match="host"):
        HistoricalContextClient(base_url=url, credentials=lambda: pytest.fail("credentials accessed"))


@pytest.mark.parametrize("status,category", [(401, "HTTP_AUTH"), (403, "HTTP_AUTH"),
    (429, "HTTP_RATE_LIMIT"), (418, "HTTP_RATE_LIMIT"), (500, "HTTP_SERVER"), (302, "HTTP_OTHER")])
def test_safe_transport_categories(status, category):
    from ladder_dragon.supervision.context_diagnostics import error_category
    client = make(Session([Response(status=status)]))
    with pytest.raises(RuntimeError) as caught:
        client.public_get("/api/v3/exchangeInfo", {"symbol": "SOLUSDT"})
    assert error_category(caught.value, "FILTER_SOURCE") == category
    if status in (418, 429):
        with pytest.raises(RuntimeError) as cooldown:
            client.public_get("/api/v3/exchangeInfo", {"symbol": "SOLUSDT"})
        assert error_category(cooldown.value, "FILTER_SOURCE") == "COOLDOWN"


def test_real_transport_failure_reaches_durable_diagnostics(tmp_path):
    from ladder_dragon.supervision.historical_context import HistoricalContextCollector
    from ladder_dragon.strategy.prediction.episode_semantics import v23_evidence_semantics_contract
    client = make(Session([requests.Timeout("private-sentinel")]))
    collector = HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client.public_get, signed_get=client.signed_get,
        clock=lambda: 1_000, panic_run_dir=tmp_path)
    result = collector.collect("SOLUSDT", {
        "classifier": v23_evidence_semantics_contract()["regime_classifier"],
        "captured_at_ms": 1_000, "regime": "RANGE", "panic": False, "panic_hits": 0})
    assert result["status"] == "BLOCKED"
    assert result["diagnostics"]["last_failure"] == {
        "observed_at_ms": 1_000, "stage": "PANIC_REFRESH", "category": "TIMEOUT"}
    assert b"private-sentinel" not in collector.diagnostics.path.read_bytes()
    assert "private-sentinel" not in repr(result)
