"""Current batch conversion observations retain snapshot and safety boundaries."""

from decimal import Decimal

import pytest

from ladder_dragon.supervision import risk_cycle, runtime
from tests.supervision.test_batch_tickers import batch_runtime
from tests.supervision.test_snapshot_tickers import snapshot_runtime


@pytest.mark.parametrize("quote", ["USDC", "BTC"])
def test_batch_cross_is_fresh_overrides_negative_and_keeps_configured_price(monkeypatch, batch_runtime, quote):
    calls = []
    monkeypatch.setattr(runtime.TM, "get_klines", lambda *a, **kw: [])
    cross = ["2.123456789123456789"]
    def public(path, params=None, **_kwargs):
        assert path == "/api/v3/ticker/price"
        calls.append(params)
        if not params:
            return [{"symbol": "AAA" + quote, "price": cross[0]},
                    {"symbol": "BBBUSDT", "price": "2"},
                    {"symbol": "BTCUSDT", "price": "999"}]
        if params["symbol"] in {"SOLUSDT", "BTCUSDT"}:
            return {"price": "75"}
        raise runtime.TM.BinanceHttpError(status=400, code=-1121)
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    cache = risk_cycle._UNVALUED_MARKET_CACHE
    cache.remember("AAA" + quote, now=risk_cycle.time.monotonic(), ttl_sec=300)
    for price in ("2.123456789123456789", "3.123456789123456789"):
        cross[0] = price
        snapshot, _, _ = runtime._build_risk_snapshot(["SOLUSDT", "BTCUSDT"], batch_runtime)
        conversion = Decimal("0.998") if quote == "USDC" else Decimal("75")
        assert snapshot.equity_usdt == Decimal("106") + 2 * Decimal(price) * conversion
        assert not cache.contains("AAA" + quote, now=risk_cycle.time.monotonic())
    assert calls.count(None) == 2
    assert {"symbol": "AAA" + quote} not in calls
    assert calls.count({"symbol": "BTCUSDT"}) == 2  # Configured quote, no bridge reread.


def test_missing_cross_and_bridge_still_read_individually(monkeypatch, batch_runtime):
    calls = []
    def public(path, params=None, **_kwargs):
        calls.append(params)
        if not params:
            return [{"symbol": "BBBUSDT", "price": "2"}]
        symbol = params["symbol"]
        if symbol in {"SOLUSDT", "BTCUSDT"}:
            return {"price": "75"}
        if symbol == "AAABTC":
            return {"price": "2"}
        raise runtime.TM.BinanceHttpError(status=400, code=-1121)
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    result, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert result.equity_usdt == Decimal("406")
    assert {"symbol": "AAABTC"} in calls and {"symbol": "BTCUSDT"} in calls


@pytest.mark.parametrize("bad", ["NaN", "0", "private-marker"])
def test_invalid_needed_conversion_blocks_without_cache_or_leak(monkeypatch, batch_runtime, capsys, bad):
    def public(path, params=None, **_kwargs):
        if params:
            return {"price": "75"}
        return [{"symbol": "AAAUSDC", "price": bad}, {"symbol": "BBBUSDT", "price": "2"}]
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    cache = risk_cycle._UNVALUED_MARKET_CACHE
    cache.remember("AAAUSDC", now=risk_cycle.time.monotonic(), ttl_sec=300)
    with pytest.raises(ValueError, match="invalid batch ticker response") as exc:
        runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert cache.contains("AAAUSDC", now=risk_cycle.time.monotonic())
    assert "private-marker" not in str(exc.value) + str(capsys.readouterr())


def test_unused_invalid_cross_does_not_replace_valid_direct(monkeypatch, batch_runtime):
    def public(path, params=None, **_kwargs):
        if params:
            return {"price": "75"}
        return [{"symbol": "AAAUSDT", "price": "1"},
                {"symbol": "BBBUSDT", "price": "2"},
                {"symbol": "AAAUSDC", "price": "0"}]
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    result, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert result.equity_usdt == Decimal("108")


def test_batch_bridge_is_shared_and_refreshed_next_snapshot(monkeypatch, batch_runtime):
    calls, bridge = [], ["10.123456789123456789"]
    def public(path, params=None, **_kwargs):
        calls.append(params)
        if not params:
            return [{"symbol": "AAABTC", "price": "2"},
                    {"symbol": "BBBBTC", "price": "3"},
                    {"symbol": "BTCUSDT", "price": bridge[0]}]
        if params["symbol"] == "SOLUSDT":
            return {"price": "75"}
        raise runtime.TM.BinanceHttpError(status=400, code=-1121)
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    for value in ("10.123456789123456789", "11.123456789123456789"):
        bridge[0] = value
        result, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
        assert result.equity_usdt == 100 + Decimal("13") * Decimal(value)
    assert calls.count(None) == 2
    assert not any(c and c["symbol"] in {"AAABTC", "BBBBTC", "BTCUSDT"} for c in calls)


def test_omitted_higher_priority_route_is_checked_before_cached_route(monkeypatch, batch_runtime):
    def public(path, params=None, **_kwargs):
        if not params:
            return [{"symbol": "AAABTC", "price": "999"},
                    {"symbol": "BTCUSDT", "price": "999"},
                    {"symbol": "BBBUSDT", "price": "2"}]
        if params["symbol"] == "SOLUSDT":
            return {"price": "75"}
        if params["symbol"] == "AAAUSDC":
            return {"price": "1"}
        raise runtime.TM.BinanceHttpError(status=400, code=-1121)
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    result, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert result.equity_usdt == Decimal("106") + Decimal("2") * Decimal("0.998")
