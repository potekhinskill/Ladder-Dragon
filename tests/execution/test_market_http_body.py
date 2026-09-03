"""Exercise real response parsing beneath the market adapter boundary."""

import gzip
import io
import json
import zlib

import pytest
import requests
from urllib3.response import HTTPResponse

from ladder_dragon.execution import market_http_body as body
from ladder_dragon.execution import tools_market as market


def response(data, status=200, encoding=None):
    result = requests.Response()
    result.status_code = status
    result.url = "https://example.invalid/api/v3/ticker/price"
    result.raw = HTTPResponse(io.BytesIO(data), preload_content=False)
    if encoding:
        result.headers["Content-Encoding"] = encoding
    return result


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(market, "_rate_limit_until", 0.0)
    monkeypatch.setattr(market, "_rate_limit_error", None)
    monkeypatch.setattr(body, "MAX_RESPONSE_BYTES", 128)


@pytest.mark.parametrize("encoding", [None, "gzip", "deflate"])
def test_exact_stream(monkeypatch, encoding):
    payload = b'{"price":"123456789.123456789"}'
    encoded = gzip.compress(payload) if encoding == "gzip" else (
        zlib.compress(payload) if encoding == "deflate" else payload
    )
    result = response(encoded, encoding=encoding)
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(market.SESSION, "request", request)
    assert str(market.get_ticker_price_decimal("SYNTHETICUSDT")) == "123456789.123456789"
    assert calls[0]["stream"] is True
    assert calls[0]["allow_redirects"] is False
    assert result.raw.closed


@pytest.mark.parametrize("status", [200, 400, 500])
@pytest.mark.parametrize("compressed", [False, True])
def test_byte_limit_precedes_json(monkeypatch, status, compressed, capsys):
    payload = b"synthetic-private-marker" * 20
    result = response(gzip.compress(payload) if compressed else payload,
                      status, "gzip" if compressed else None)
    result.headers["Content-Length"] = "1"
    calls = []
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: calls.append(kw) or result)
    monkeypatch.setattr(result, "json", lambda: pytest.fail("must not parse oversized body"))
    with pytest.raises(body.MarketResponseError, match="byte limit") as caught:
        market._public_get("/api/v3/ticker/price")
    assert "synthetic-private-marker" not in str(caught.value)
    assert result.raw.closed
    assert len(calls) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("payload,encoding", [
    (b"invalid", "gzip"), (gzip.compress(b"{}")[0:-2], "gzip"),
    (gzip.compress(b"{}") + b"extra", "gzip"), (b"{}", "br"),
])
def test_bad_encoding(monkeypatch, payload, encoding):
    result = response(payload, encoding=encoding)
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: result)
    with pytest.raises(body.MarketResponseError):
        market._public_get("/api/v3/time")
    assert result.raw.closed


def test_missing_market_classification(monkeypatch):
    result = response(json.dumps({"code": -1121, "msg": "Invalid symbol"}).encode(), 400)
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: result)
    with pytest.raises(market.BinanceHttpError) as caught:
        market._public_get("/api/v3/ticker/price")
    assert caught.value.code == -1121
    assert result.raw.closed


def test_retry_budget(monkeypatch):
    clock = [0.0]
    calls = []
    results = []
    monkeypatch.setattr(market.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(market.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))

    def request(*args, **kwargs):
        calls.append(kwargs["timeout"])
        clock[0] += 2
        result = response(b"{}", 500)
        results.append(result)
        return result

    monkeypatch.setattr(market.SESSION, "request", request)
    with pytest.raises(requests.Timeout, match="budget exhausted"):
        market._public_get("/api/v3/time", timeout=1)
    assert calls == [1, 1]
    assert clock[0] == 4.5
    assert all(result.raw.closed for result in results)


def test_slow_raw_chunks_stop_at_budget(monkeypatch):
    clock = [0.0]
    result = response(b"{}")
    reads = []
    monkeypatch.setattr(market.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(market.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))

    def read1(*args, **kwargs):
        clock[0] += 1
        reads.append(1)
        return b" "

    monkeypatch.setattr(result.raw, "read1", read1)
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: result)
    with pytest.raises(requests.Timeout, match="budget exhausted"):
        market._public_get("/api/v3/time", timeout=0.5)
    assert len(reads) == 3
    assert result.raw.closed


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 1e308, True])
def test_invalid_timeout(monkeypatch, timeout):
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: pytest.fail("no network"))
    with pytest.raises(ValueError):
        market._public_get("/api/v3/time", timeout=timeout)


def test_no_mutations(monkeypatch):
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: pytest.fail("no network"))
    with pytest.raises(ValueError, match="reads only"):
        market._do_request("POST", "https://example.invalid/api/v3/order")


def test_transport_diagnostics(monkeypatch):
    calls = []
    monkeypatch.setattr(market.time, "sleep", lambda delay: None)

    def request(*args, **kwargs):
        calls.append(1)
        raise requests.ConnectionError("https://example.invalid/?signature=synthetic-private-marker")

    monkeypatch.setattr(market.SESSION, "request", request)
    with pytest.raises(requests.RequestException) as caught:
        market._public_get("/api/v3/time")
    assert len(calls) == 3
    assert str(caught.value) == "market transport failed"
    assert caught.value.__suppress_context__


def test_provider_text_not_exposed(monkeypatch):
    payload = json.dumps({"code": -2015, "msg": "synthetic-private-marker"}).encode()
    result = response(payload, 401)
    alerts = []
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: result)
    monkeypatch.setattr(market, "notify_binance_auth_error", lambda **kw: alerts.append(kw))
    with pytest.raises(market.BinanceHttpError) as caught:
        market._public_get("/api/v3/time")
    assert caught.value.code == -2015
    assert "synthetic-private-marker" not in str(caught.value)
    assert "synthetic-private-marker" not in str(alerts)


def test_exact_byte_boundary(monkeypatch):
    result = response(b" " * 126 + b"{}")
    monkeypatch.setattr(market.SESSION, "request", lambda *a, **kw: result)
    assert market._public_get("/api/v3/time") == {}
    assert result.raw.closed


def test_server_retry_closes_each_response(monkeypatch):
    results = [response(b"{}", 500), response(b"{}", 503), response(b"{}")]
    pending = iter(results)
    monkeypatch.setattr(market.time, "sleep", lambda delay: None)

    def request(*args, **kwargs):
        result = next(pending)
        index = results.index(result)
        assert all(previous.raw.closed for previous in results[:index])
        return result

    monkeypatch.setattr(market.SESSION, "request", request)
    assert market._public_get("/api/v3/time") == {}
    assert all(result.raw.closed for result in results)
