"""Fixed-size, secret-free diagnostic counters never replace source outcomes."""

from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from ladder_dragon.supervision import valuation_metrics as metrics
from ladder_dragon.supervision import risk_cycle


@pytest.mark.parametrize("error,category", [
    (requests.Timeout("synthetic-private-marker"), "transient"),
    (ValueError("synthetic-private-marker"), "other_errors"),
])
def test_error_identity_and_privacy(monkeypatch, error, category):
    clock = iter([1.0, 1.125])
    monkeypatch.setattr(metrics.time, "monotonic", lambda: next(clock))
    counters = metrics.ValuationMetrics()

    def fail(*args):
        raise error

    with pytest.raises(type(error)) as caught:
        counters.read("direct", fail, "PRIVATEASSET", "synthetic-private-marker")
    assert caught.value is error
    result = counters.snapshot(failed=True)
    assert result["direct_reads"] == 1
    assert result["direct_read_ms"] == 125
    assert result[f"direct_{category}"] == 1
    assert result["attempt_failed"] == 1
    assert "PRIVATEASSET" not in str(result)
    assert "synthetic-private-marker" not in str(result)
    assert all(type(value) is int for value in result.values())


@pytest.mark.parametrize("code,status,category", [
    (-1121, 400, "missing"), (-1021, 400, "transient"),
    (None, 429, "transient"), (None, 503, "transient"),
    (-2015, 401, "other_errors"),
])
def test_provider_categories(code, status, category):
    counters = metrics.ValuationMetrics()
    error = RuntimeError("synthetic-private-marker")
    error.code, error.status = code, status

    def fail():
        raise error

    with pytest.raises(RuntimeError):
        counters.read("cross_btc", fail)
    result = counters.snapshot(failed=True)
    assert result[f"cross_btc_{category}"] == 1
    assert sum(result[f"cross_btc_{name}"] for name in ("missing", "transient", "other_errors")) == 1


def test_concurrent_fixed_size_and_reset():
    counters = metrics.ValuationMetrics()
    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(lambda value: counters.read("bridge", lambda: value), range(100)))
    assert values == list(range(100))
    result = counters.snapshot(failed=False)
    assert result["bridge_reads"] == 100
    assert len(result) == 1 + len(metrics.ROUTES) * len(metrics.COUNTERS)
    result["bridge_reads"] = 0
    assert counters.snapshot(failed=False)["bridge_reads"] == 100
    assert metrics.ValuationMetrics().snapshot(failed=False)["bridge_reads"] == 0


def test_current_and_negative_cache_hits(monkeypatch):
    cache = risk_cycle._DefinitiveMissingMarketCache()
    monkeypatch.setattr(risk_cycle, "_UNVALUED_MARKET_CACHE", cache)
    counters = metrics.ValuationMetrics()
    cache.remember("AAAUSDT", now=metrics.time.monotonic(), ttl_sec=100)

    def forbidden(*args):
        pytest.fail("no future market read")

    assert risk_cycle.direct_usdt_valuation_price(
        "AAA", {}, forbidden, cache_missing=True, metrics=counters,
    ) is None
    assert risk_cycle.direct_usdt_valuation_price(
        "AAA", {"AAAUSDT": "2"}, forbidden, cache_missing=True, metrics=counters,
    ) == 2
    result = counters.snapshot(failed=False)
    assert result["direct_negative_hits"] == result["direct_cache_hits"] == 1
    assert result["direct_reads"] == 0


def test_shared_cache_counts_actual_adapter_calls():
    counters = metrics.ValuationMetrics()
    prices = risk_cycle._SnapshotTickerPrices(lambda symbol: "2", {}, counters)
    assert prices.get("BTCUSDT", route="bridge") == 2
    assert prices.get("BTCUSDT", route="bridge") == 2
    result = counters.snapshot(failed=False)
    assert result["bridge_reads"] == result["bridge_cache_hits"] == 1
