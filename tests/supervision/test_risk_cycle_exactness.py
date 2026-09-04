import ast
from decimal import Decimal
import inspect
import re
import threading
import time

import pytest

from ladder_dragon.risk.risk_manager import RiskDecision
from ladder_dragon.supervision import risk_cycle, runtime
from ladder_dragon.supervision.risk_cycle import (
    RiskConfigurationError,
    direct_usdt_valuation_price,
    reconciliation_tolerance_fraction,
    remaining_open_buy_notional,
    risk_alert_signature,
    risk_configuration_block,
)


def test_direct_account_asset_quote_is_fetched_and_cached():
    prices = {}
    requested = []

    price = direct_usdt_valuation_price(
        "KERNEL",
        prices,
        lambda symbol: requested.append(symbol) or Decimal("0.1734"),
    )

    assert price == Decimal("0.1734")
    assert prices == {"KERNELUSDT": Decimal("0.1734")}
    assert requested == ["KERNELUSDT"]


def test_unavailable_direct_quote_keeps_bridge_fallback_reachable():
    def unavailable(_symbol):
        raise RuntimeError("temporary direct quote failure")

    assert direct_usdt_valuation_price("KERNEL", {}, unavailable) is None


@pytest.mark.parametrize("raw_price", [Decimal("0.1734"), "0.1734"])
def test_fresh_snapshot_quote_overrides_negative_cache(monkeypatch, raw_price):
    cache = risk_cycle._DefinitiveMissingMarketCache()
    monkeypatch.setattr(risk_cycle, "_UNVALUED_MARKET_CACHE", cache)
    monkeypatch.setattr(risk_cycle.time, "monotonic", lambda: 10.0)
    cache.remember("KERNELUSDT", now=9.0, ttl_sec=300)
    prices = {"KERNELUSDT": raw_price}
    requested = []

    result = direct_usdt_valuation_price(
        "KERNEL", prices,
        lambda symbol: requested.append(symbol) or Decimal("999"),
        cache_missing=True, cache_ttl_sec=300,
    )

    assert result == Decimal("0.1734")
    assert prices == {"KERNELUSDT": Decimal("0.1734")}
    assert requested == []
    assert not cache.contains("KERNELUSDT", now=10.0)


@pytest.mark.parametrize("raw_price", [None, "0", "-1", "NaN", "Infinity", "invalid"])
def test_invalid_snapshot_quote_does_not_clear_negative_cache(
    monkeypatch, capsys, raw_price,
):
    cache = risk_cycle._DefinitiveMissingMarketCache()
    monkeypatch.setattr(risk_cycle, "_UNVALUED_MARKET_CACHE", cache)
    monkeypatch.setattr(risk_cycle.time, "monotonic", lambda: 10.0)
    cache.remember("KERNELUSDT", now=9.0, ttl_sec=300)
    requested = []

    result = direct_usdt_valuation_price(
        "KERNEL", {"KERNELUSDT": raw_price},
        lambda symbol: requested.append(symbol) or Decimal("999"),
        cache_missing=True, cache_ttl_sec=300,
    )

    assert result is None
    assert requested == []
    assert cache.contains("KERNELUSDT", now=10.0)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_negative_cache_rechecks_only_definitive_missing_market(monkeypatch):
    class MissingMarket(RuntimeError):
        code = -1121

    now = [10.0]
    requested = []
    risk_cycle._UNVALUED_MARKET_CACHE.clear()
    monkeypatch.setattr(risk_cycle.time, "monotonic", lambda: now[0])

    def unavailable(symbol):
        requested.append(symbol)
        raise MissingMarket("invalid symbol")

    kwargs = {"cache_missing": True, "cache_ttl_sec": 300}
    assert direct_usdt_valuation_price("KERNEL", {}, unavailable, **kwargs) is None
    assert direct_usdt_valuation_price("KERNEL", {}, unavailable, **kwargs) is None
    assert requested == ["KERNELUSDT"]

    now[0] = 311.0
    assert direct_usdt_valuation_price("KERNEL", {}, unavailable, **kwargs) is None
    assert requested == ["KERNELUSDT", "KERNELUSDT"]


def test_negative_cache_never_hides_transient_market_failure():
    requested = []
    risk_cycle._UNVALUED_MARKET_CACHE.clear()

    def unavailable(symbol):
        requested.append(symbol)
        raise RuntimeError("temporary transport failure")

    kwargs = {"cache_missing": True, "cache_ttl_sec": 300}
    assert direct_usdt_valuation_price("TRANSIENT", {}, unavailable, **kwargs) is None
    assert direct_usdt_valuation_price("TRANSIENT", {}, unavailable, **kwargs) is None
    assert requested == ["TRANSIENTUSDT", "TRANSIENTUSDT"]


def test_public_reads_have_bounded_concurrency_and_stable_order():
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def read(value):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return value * 2

    result = risk_cycle._bounded_public_reads(
        [3, 1, 4, 2], read, concurrency=2
    )

    assert result == [6, 2, 8, 4]
    assert maximum_active == 2


def test_parallel_pool_receives_only_explicit_public_readers():
    tree = ast.parse(inspect.getsource(risk_cycle.build_risk_snapshot))
    readers = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_bounded_public_reads"
        ):
            assert isinstance(node.args[1], ast.Name)
            readers.append(node.args[1].id)

    assert len(readers) == 4
    assert set(readers) == {
        "get_last_price_decimal",
        "value_account_asset",
        "read_history",
        "liquidity_is_safe",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RISK_PUBLIC_READ_CONCURRENCY", "0"),
        ("RISK_PUBLIC_READ_CONCURRENCY", "5"),
        ("RISK_PUBLIC_READ_CONCURRENCY", "invalid"),
        ("RISK_UNVALUED_NEGATIVE_CACHE_SEC", "-1"),
        ("RISK_UNVALUED_NEGATIVE_CACHE_SEC", "901"),
        ("RISK_UNVALUED_NEGATIVE_CACHE_SEC", "invalid"),
    ],
)
def test_risk_startup_acceleration_configuration_fails_closed(
    monkeypatch, name, value
):
    monkeypatch.setenv(name, value)

    with pytest.raises(RiskConfigurationError):
        if name == "RISK_PUBLIC_READ_CONCURRENCY":
            risk_cycle._public_read_concurrency()
        else:
            risk_cycle._unvalued_negative_cache_ttl()


def test_risk_snapshot_exposes_every_requested_startup_subphase():
    source = inspect.getsource(risk_cycle.build_risk_snapshot)
    phases = set(re.findall(r'mark_phase\("([a-z_]+)"\)', source))

    assert {
        "fill_sync",
        "account",
        "ticker",
        "orders",
        "protection",
        "valuation",
        "history",
        "depth",
        "statistics",
    } <= phases


def test_missing_direct_and_bridge_quotes_keep_risk_fail_closed(monkeypatch):
    requested = []
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "0")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "0")
    monkeypatch.delenv("RISK_UNVALUED_ASSETS", raising=False)
    monkeypatch.delenv("RISK_UNVALUED_ASSETS_ACK", raising=False)
    monkeypatch.setattr(
        runtime,
        "get_balances_full",
        lambda: {
            "USDT": {"free": "100", "locked": "0"},
            "KERNEL": {"free": "1", "locked": "0"},
        },
    )
    monkeypatch.setattr(runtime, "get_last_price", lambda _symbol: "75")

    def unavailable(symbol):
        if symbol == "SOLUSDT":
            return Decimal("75")
        requested.append(symbol)
        raise RuntimeError("temporary price failure")

    monkeypatch.setattr(runtime, "get_last_price_decimal", unavailable)
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda *_args, **_kwargs: [])

    with pytest.raises(RuntimeError, match="cannot value account asset KERNEL"):
        runtime._build_risk_snapshot(
            ["SOLUSDT"], runtime.RiskLimits.from_mapping({})
        )

    assert requested[0] == "KERNELUSDT"


def test_risk_snapshot_caches_definitive_missing_routes_for_valued_assets(
    monkeypatch,
):
    class MissingMarket(RuntimeError):
        code = -1121

    requested = []
    monkeypatch.setattr(
        risk_cycle,
        "_UNVALUED_MARKET_CACHE",
        risk_cycle._DefinitiveMissingMarketCache(),
    )
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "0")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "0")
    monkeypatch.delenv("RISK_UNVALUED_ASSETS", raising=False)
    monkeypatch.delenv("RISK_UNVALUED_ASSETS_ACK", raising=False)
    monkeypatch.setattr(
        runtime,
        "get_balances_full",
        lambda: {
            "USDT": {"free": "100", "locked": "0"},
            "KERNEL": {"free": "1", "locked": "0"},
        },
    )
    monkeypatch.setattr(runtime, "get_last_price", lambda _symbol: "75")

    def unavailable(symbol):
        if symbol == "SOLUSDT":
            return Decimal("75")
        requested.append(symbol)
        raise MissingMarket("invalid symbol")

    monkeypatch.setattr(runtime, "get_last_price_decimal", unavailable)
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda *_args, **_kwargs: [])

    with pytest.raises(RuntimeError, match="cannot value account asset KERNEL"):
        runtime._build_risk_snapshot(
            ["SOLUSDT"], runtime.RiskLimits.from_mapping({})
        )
    first_attempt = tuple(requested)
    with pytest.raises(RuntimeError, match="cannot value account asset KERNEL"):
        runtime._build_risk_snapshot(
            ["SOLUSDT"], runtime.RiskLimits.from_mapping({})
        )

    assert set(first_attempt) == {
        "KERNELUSDT",
        "KERNELUSDC",
        "KERNELFDUSD",
        "KERNELBTC",
        "KERNELETH",
    }
    assert tuple(requested) == first_attempt


def test_partial_buy_exposure_counts_only_unfilled_quantity():
    order = {
        "side": "BUY",
        "price": "75.00",
        "origQty": "1.000",
        "executedQty": "0.400",
    }

    assert remaining_open_buy_notional(order) == Decimal("45.00000")
    source = inspect.getsource(risk_cycle.build_risk_snapshot)
    assert source.count("remaining_open_buy_notional(order)") == 3
    assert 'money(order.get("origQty"))' not in source


@pytest.mark.parametrize(
    "order",
    [
        {"price": "75", "origQty": "1", "executedQty": "1.1"},
        {"price": "75", "origQty": "-1", "executedQty": "0"},
        {"price": "NaN", "origQty": "1", "executedQty": "0"},
    ],
)
def test_invalid_open_buy_quantity_fails_closed(order):
    with pytest.raises((ValueError, ArithmeticError)):
        remaining_open_buy_notional(order)


def test_reconciliation_tolerance_uses_strict_fraction_contract():
    assert reconciliation_tolerance_fraction({}) == (Decimal("0.001"), False)
    assert reconciliation_tolerance_fraction(
        {"RISK_RECONCILE_TOLERANCE_FRACTION": "0.002"}
    ) == (Decimal("0.002"), False)
    assert reconciliation_tolerance_fraction(
        {"RISK_RECONCILE_TOLERANCE_PCT": "0.02"}
    ) == (Decimal("0.02"), True)
    assert reconciliation_tolerance_fraction({
        "RISK_RECONCILE_TOLERANCE_FRACTION": "0.003",
        "RISK_RECONCILE_TOLERANCE_PCT": "0.02",
    }) == (Decimal("0.003"), False)


@pytest.mark.parametrize("value", ["-0.001", "0.5", "NaN", "Infinity"])
def test_unsafe_reconciliation_tolerance_fails_closed(value):
    with pytest.raises(RiskConfigurationError):
        reconciliation_tolerance_fraction(
            {"RISK_RECONCILE_TOLERANCE_FRACTION": value}
        )


def test_var_history_block_is_not_an_api_failure_or_cooldown():
    error = RiskConfigurationError("VaR history unavailable for SOLUSDT")

    reason, decision, status = risk_configuration_block(error, 2)

    assert decision.buy_blocked is True
    assert decision.halted is False
    assert status["consecutive_api_failures"] == 2
    assert status["configuration_error"] == str(error)
    assert "configuration" in reason
    source = inspect.getsource(runtime.main)
    config_offset = source.rindex("except RiskConfigurationError")
    operation_offset = source.index(
        "except SUPERVISOR_OPERATION_ERRORS", config_offset
    )
    assert config_offset < operation_offset
    config_block = source[config_offset:operation_offset]
    assert "start_cooldown" not in config_block
    assert "consecutive_api_failures +=" not in config_block


def test_risk_alert_signature_ignores_only_retry_counter():
    first = RiskDecision(
        halted=False,
        buy_blocked=True,
        reasons=(
            "risk telemetry unavailable (1/3): position reconciliation failed: "
            "SOLUSDT",
        ),
    )
    repeated = RiskDecision(
        halted=False,
        buy_blocked=True,
        reasons=(
            "risk telemetry unavailable (57/3): position reconciliation failed: "
            "SOLUSDT",
        ),
    )

    assert risk_alert_signature(first) == risk_alert_signature(repeated)


def test_risk_alert_signature_preserves_material_changes():
    baseline = RiskDecision(
        halted=False,
        buy_blocked=True,
        reasons=("risk telemetry unavailable (2/3): account mismatch A",),
    )
    changed_reason = RiskDecision(
        halted=False,
        buy_blocked=True,
        reasons=("risk telemetry unavailable (3/3): account mismatch B",),
    )
    changed_state = RiskDecision(
        halted=True,
        buy_blocked=True,
        reasons=baseline.reasons,
    )

    assert risk_alert_signature(baseline) != risk_alert_signature(changed_reason)
    assert risk_alert_signature(baseline) != risk_alert_signature(changed_state)
