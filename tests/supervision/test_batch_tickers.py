"""Prove batch wire parsing and whole-snapshot exactness without live I/O."""

from decimal import Decimal
import gzip
import io
import json
import threading
import time

import pytest
import requests
from urllib3.response import HTTPResponse

from ladder_dragon.execution import market_http_body
from ladder_dragon.supervision import risk_cycle, runtime
from tests.supervision.test_snapshot_tickers import snapshot_runtime

PUBLIC_GET = runtime.TM._public_get


@pytest.fixture
def batch_runtime(monkeypatch, snapshot_runtime):
    monkeypatch.setenv("RISK_BATCH_TICKERS", "1")
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {
        "USDT": {"free": "100", "locked": "0"},
        "AAA": {"free": "2", "locked": "0"},
        "BBB": {"free": "3", "locked": "0"},
    })
    return snapshot_runtime


def test_batch_wire_is_exact_and_fresh(monkeypatch, batch_runtime):
    # Exercise the actual bounded HTTP transport and every numeric conversion.
    market = runtime.TM
    monkeypatch.setattr(market, "_public_get", PUBLIC_GET)
    monkeypatch.setattr(market, "_rate_limit_until", 0)
    calls, responses = [], []
    exact = ["1.123456789123456789"]
    def request(method, url, **kwargs):
        assert method == "GET"
        assert "X-MBX-APIKEY" not in kwargs["headers"]
        assert kwargs["stream"] and not kwargs["allow_redirects"]
        params = kwargs["params"]
        calls.append(params)
        payload = {"symbol": "SOLUSDT", "price": "75"} if params else [
            {"symbol": "AAAUSDT", "price": exact[0]},
            {"symbol": "BBBUSDT", "price": "2"},
            {"symbol": "SOLUSDT", "price": "999"},
            {"symbol": "UNUSEDUSDT", "price": "0"},
            {"symbol": "\u5e01USDT", "price": "0"},
        ]
        result = requests.Response()
        result.status_code = 200
        result.url = url
        result.headers["Content-Encoding"] = "gzip"
        result.raw = HTTPResponse(io.BytesIO(gzip.compress(json.dumps(payload).encode())), preload_content=False)
        responses.append(result)
        return result
    monkeypatch.setattr(market.SESSION, "request", request)
    monkeypatch.setattr(market.INITIAL_PUBLIC_SESSION, "request", request)
    monkeypatch.setattr(market.VALUATION_BATCH_SESSION, "request", request)
    risk_cycle._UNVALUED_MARKET_CACHE.remember("AAAUSDT", now=risk_cycle.time.monotonic(), ttl_sec=300)
    first, _, prices = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert first.equity_usdt == Decimal("100") + Decimal(exact[0]) * 2 + 6
    assert prices == {"SOLUSDT": Decimal("75")}
    assert not risk_cycle._UNVALUED_MARKET_CACHE.contains("AAAUSDT", now=risk_cycle.time.monotonic())
    exact[0] = "3.123456789123456789"
    second, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert second.equity_usdt == first.equity_usdt + 4
    assert calls == [{"symbol": "SOLUSDT"}, {}, {"symbol": "SOLUSDT"}, {}]
    assert all(r.raw.closed for r in responses)


@pytest.mark.parametrize("payload", [None, {}, [None], [{"symbol": "AAAUSDT", "price": "NaN"}],
    [{"symbol": "AAAUSDT", "price": 2}], [{"symbol": "AAAUSDT", "price": "0"}],
    [{"symbol": "AAAUSDT", "price": "private-marker"}],
    [{"symbol": "AAAUSDT", "price": "1"}] * 2])
def test_invalid_batch_blocks_snapshot(monkeypatch, batch_runtime, payload, capsys):
    reports = {}
    monkeypatch.setattr(runtime, "_record_risk_startup_phase", lambda phase, values: reports.update({phase: values}))
    def public(path, params=None, **_kwargs):
        return {"price": "75"} if params else payload
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    with pytest.raises(ValueError, match="invalid batch ticker response") as error:
        runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert "private-marker" not in str(error.value)
    assert reports["valuation_routes"]["attempt_failed"] == 1
    assert reports["valuation_routes"]["batch_other_errors"] == 1
    assert not risk_cycle._UNVALUED_MARKET_CACHE.contains("AAAUSDT", now=risk_cycle.time.monotonic())
    assert "private-marker" not in repr(reports) + str(capsys.readouterr())


def test_omission_uses_individual_read(monkeypatch, batch_runtime):
    calls = []
    def public(path, params=None, **_kwargs):
        calls.append(params)
        if not params:
            return [{"symbol": "AAAUSDT", "price": "1"}]
        return {"price": "2" if params["symbol"] == "BBBUSDT" else "75"}
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    snapshot, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert snapshot.equity_usdt == 108
    assert calls == [{"symbol": "SOLUSDT"}, None, {"symbol": "BBBUSDT"}]


def test_batch_transport_failure_stops_reads(monkeypatch, batch_runtime):
    calls = []
    def public(path, params=None, **_kwargs):
        calls.append(params)
        if not params:
            raise requests.Timeout("market transport failed")
        return {"price": "75"}
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    with pytest.raises(requests.Timeout):
        runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert calls == [{"symbol": "SOLUSDT"}, None]


def test_batch_overlaps_signed_order_preparation(monkeypatch, batch_runtime):
    batch_started = threading.Event()
    orders_finished = threading.Event()

    def batch_reader(_symbols, *, known_prices):
        assert known_prices == {"SOLUSDT": Decimal("75")}
        assert threading.current_thread() is not threading.main_thread()
        batch_started.set()
        assert orders_finished.wait(2), "signed orders did not overlap batch"
        return {
            "AAAUSDT": Decimal("1"),
            "BBBUSDT": Decimal("2"),
        }

    def signed_get(endpoint):
        assert threading.current_thread() is threading.main_thread()
        assert endpoint == "/api/v3/openOrders"
        assert batch_started.wait(2), "batch did not start before signed orders"
        orders_finished.set()
        return []

    monkeypatch.setattr(
        runtime, "get_initial_last_price_decimal", lambda _symbol: Decimal("75")
    )
    monkeypatch.setattr(runtime.TM, "get_ticker_prices_decimal", batch_reader)
    monkeypatch.setattr(runtime.TM, "_signed_get", signed_get)

    snapshot, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)

    assert snapshot.equity_usdt == Decimal("108")


def test_signed_failure_drains_batch_without_printing_payload(
    monkeypatch, batch_runtime, capsys,
):
    batch_started = threading.Event()
    batch_finished = threading.Event()

    def batch_reader(_symbols, *, known_prices):
        assert known_prices == {"SOLUSDT": Decimal("75")}
        batch_started.set()
        time.sleep(0.03)
        batch_finished.set()
        return {
            "AAAUSDT": Decimal("1"),
            "BBBUSDT": Decimal("2"),
        }

    def signed_get(_endpoint):
        assert batch_started.wait(2)
        raise RuntimeError("synthetic-private-marker")

    monkeypatch.setattr(
        runtime, "get_initial_last_price_decimal", lambda _symbol: Decimal("75")
    )
    monkeypatch.setattr(runtime.TM, "get_ticker_prices_decimal", batch_reader)
    monkeypatch.setattr(runtime.TM, "_signed_get", signed_get)

    with pytest.raises(RuntimeError, match="synthetic-private-marker"):
        runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)

    assert batch_finished.is_set()
    assert "synthetic-private-marker" not in str(capsys.readouterr())


def test_batch_byte_limit_precedes_parsing(monkeypatch, batch_runtime):
    monkeypatch.setattr(runtime.TM, "_public_get", PUBLIC_GET)
    monkeypatch.setattr(runtime.TM, "_rate_limit_until", 0)
    monkeypatch.setattr(market_http_body, "MAX_RESPONSE_BYTES", 64)
    result = requests.Response()
    result.status_code = 200
    result.headers["Content-Encoding"] = "gzip"
    result.raw = HTTPResponse(io.BytesIO(gzip.compress(b"private-marker" * 100)), preload_content=False)
    monkeypatch.setattr(
        runtime.TM.VALUATION_BATCH_SESSION,
        "request",
        lambda *args, **kwargs: result,
    )
    with pytest.raises(market_http_body.MarketResponseError) as error:
        runtime.TM.get_ticker_prices_decimal({"AAAUSDT", "BBBUSDT"})
    assert "private-marker" not in str(error.value)
    assert result.raw.closed


def test_forty_assets_preserve_individual_result(monkeypatch, batch_runtime):
    payload = [{"symbol": f"A{i}USDT", "price": str(i + 1)} for i in range(40)]
    balances = {f"A{i}": {"free": "1", "locked": "0"} for i in range(40)}
    balances["USDT"] = {"free": "100", "locked": "0"}
    monkeypatch.setattr(runtime, "get_balances_full", lambda: balances)
    calls = []
    def public(path, params=None, **_kwargs):
        calls.append(params)
        if not params:
            return payload
        symbol = params["symbol"]
        return {"price": "75"} if symbol == "SOLUSDT" else next(row for row in payload if row["symbol"] == symbol)
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    batch, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert len(calls) == 2  # One configured read plus one account batch.
    calls.clear()
    monkeypatch.setenv("RISK_BATCH_TICKERS", "0")
    individual, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert len(calls) == 41
    assert batch.equity_usdt == individual.equity_usdt == Decimal("920")
    assert batch.exposure_usdt == individual.exposure_usdt == Decimal("820")
