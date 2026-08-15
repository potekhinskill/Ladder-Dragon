from decimal import Decimal
import inspect

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
        requested.append(symbol)
        raise RuntimeError("temporary price failure")

    monkeypatch.setattr(runtime, "get_last_price_decimal", unavailable)
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda *_args, **_kwargs: [])

    with pytest.raises(RuntimeError, match="cannot value account asset KERNEL"):
        runtime._build_risk_snapshot(
            ["SOLUSDT"], runtime.RiskLimits.from_mapping({})
        )

    assert requested[0] == "KERNELUSDT"


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
