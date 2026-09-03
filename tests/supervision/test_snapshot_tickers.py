from decimal import Decimal
import threading
import time

import pytest

from ladder_dragon.supervision import risk_cycle, runtime


def test_seeded_current_quote_does_not_read_a_later_price():
    exact = Decimal("123.123456789123456789")

    def forbidden(_symbol):
        raise AssertionError("later market data must not replace the snapshot")

    prices = risk_cycle._SnapshotTickerPrices(forbidden, {"BTCUSDT": exact})
    assert prices.get("BTCUSDT") == exact
    assert prices.get("BTCUSDT") == exact


def test_same_ticker_is_read_once_under_concurrency():
    calls = []
    barrier = threading.Barrier(3)

    def reader(symbol):
        calls.append(symbol)
        time.sleep(0.02)
        return Decimal("123456789.123456789")

    prices = risk_cycle._SnapshotTickerPrices(reader, {})

    def consume(_item):
        barrier.wait(timeout=2)
        return prices.get("BTCUSDT")

    results = risk_cycle._bounded_public_reads([1, 2, 3], consume, concurrency=3)
    assert calls == ["BTCUSDT"]
    assert results == [Decimal("123456789.123456789")] * 3


def test_different_tickers_do_not_serialize_network_reads():
    barrier = threading.Barrier(2)

    def reader(symbol):
        barrier.wait(timeout=2)
        return Decimal("1") if symbol == "BTCUSDT" else Decimal("2")

    prices = risk_cycle._SnapshotTickerPrices(reader, {})
    assert risk_cycle._bounded_public_reads(
        ["BTCUSDT", "ETHUSDT"], prices.get, concurrency=2,
    ) == [Decimal("1"), Decimal("2")]


def test_failed_ticker_read_is_not_cached(capsys):
    calls = []

    def reader(symbol):
        calls.append(symbol)
        if len(calls) == 1:
            raise RuntimeError("synthetic transport failure")
        return Decimal("2")

    prices = risk_cycle._SnapshotTickerPrices(reader, {})
    with pytest.raises(RuntimeError, match="synthetic transport failure"):
        prices.get("BTCUSDT")
    assert prices.get("BTCUSDT") == Decimal("2")
    assert calls == ["BTCUSDT", "BTCUSDT"]
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("invalid", ["0", "-1", "NaN", "Infinity", "invalid"])
def test_invalid_ticker_is_rejected_and_not_cached(invalid):
    values = iter([invalid, Decimal("2")])
    prices = risk_cycle._SnapshotTickerPrices(lambda _symbol: next(values), {})
    with pytest.raises(ValueError):
        prices.get("BTCUSDT")
    assert prices.get("BTCUSDT") == Decimal("2")


@pytest.fixture
def snapshot_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_STATS_DB", str(tmp_path / "unused.sqlite3"))
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "0")
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "0")
    monkeypatch.setenv("RISK_CONVERSION_DEPTH_REQUIRED", "0")
    monkeypatch.setenv("RISK_PUBLIC_READ_CONCURRENCY", "2")
    monkeypatch.setattr(runtime, "LIVE_MODE", False)
    monkeypatch.setattr(runtime, "_configured_unvalued_assets", lambda: set())
    monkeypatch.setattr(runtime, "_control_mode", lambda _name: "OFF")
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda *_a, **_kw: [])
    monkeypatch.setattr(runtime, "load_daily_trade_metrics", lambda *_a, **_kw: {})
    monkeypatch.setattr(
        risk_cycle, "_UNVALUED_MARKET_CACHE",
        risk_cycle._DefinitiveMissingMarketCache(),
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected analytics or network adapter")

    monkeypatch.setattr(runtime, "get_last_price", forbidden)
    monkeypatch.setattr(runtime.TM, "_public_get", forbidden)
    monkeypatch.setattr(runtime.TM, "get_klines", forbidden)
    return runtime.RiskLimits.from_mapping({})


def test_snapshot_preserves_exact_configured_price(monkeypatch, snapshot_runtime):
    exact = Decimal("123456789.123456789")
    requests = []

    def public_get(path, params):
        requests.append((path, params))
        return {"symbol": "SOLUSDT", "price": str(exact)}

    # Exercise the production adapter chain, not a mocked Decimal getter.
    monkeypatch.setattr(runtime.TM, "_public_get", public_get)
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {
        "USDT": {"free": "100", "locked": "0"},
        "SOL": {"free": "1", "locked": "0"},
    })

    snapshot, _, prices = runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
    assert prices == {"SOLUSDT": exact}
    assert isinstance(prices["SOLUSDT"], Decimal)
    assert snapshot.equity_usdt == Decimal("100") + exact
    assert snapshot.exposure_usdt == exact
    assert requests == [("/api/v3/ticker/price", {"symbol": "SOLUSDT"})]


def test_shared_bridge_is_fresh_for_each_snapshot(monkeypatch, snapshot_runtime):
    calls = []
    barrier = threading.Barrier(2)
    bridge = [Decimal("123.123456789123456789")]
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {
        "USDT": {"free": "100", "locked": "0"},
        "AAA": {"free": "1", "locked": "0"},
        "BBB": {"free": "1", "locked": "0"},
    })

    def reader(symbol):
        calls.append(symbol)
        if symbol == "SOLUSDT":
            return Decimal("75")
        if symbol in {"AAABTC", "BBBBTC"}:
            barrier.wait(timeout=2)
            return Decimal("1")
        if symbol == "BTCUSDT":
            time.sleep(0.02)
            return bridge[0]
        raise RuntimeError("synthetic missing route")

    monkeypatch.setattr(runtime, "get_last_price_decimal", reader)
    first, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
    assert first.exposure_usdt == bridge[0] * 2
    assert calls.count("BTCUSDT") == 1

    bridge[0] = Decimal("124.123456789123456789")
    second, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
    assert second.exposure_usdt == bridge[0] * 2
    assert calls.count("BTCUSDT") == 2


def test_unavailable_bridge_blocks_snapshot(monkeypatch, snapshot_runtime):
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {
        "AAA": {"free": "1", "locked": "0"},
    })

    def reader(symbol):
        if symbol == "SOLUSDT":
            return Decimal("75")
        if symbol == "AAABTC":
            return Decimal("1")
        raise RuntimeError("synthetic unavailable market")

    monkeypatch.setattr(runtime, "get_last_price_decimal", reader)
    with pytest.raises(RuntimeError, match="synthetic unavailable market"):
        runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
