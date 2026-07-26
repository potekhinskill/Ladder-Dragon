from decimal import Decimal

import pytest

from ladder_dragon.strategy import expectancy_controls
from ladder_dragon.strategy.expectancy_controls import (
    RegimeExecutionStateMachine,
    authoritative_commission_schedule,
    inventory_skew_scale,
    required_round_trip_edge,
    vwap_premium_blocked,
)


def commission_payload():
    return {
        "standardCommission": {
            "maker": "0.00075",
            "taker": "0.001",
            "buyer": "0",
            "seller": "0",
        },
        "taxCommission": {
            "maker": "0",
            "taker": "0",
            "buyer": "0",
            "seller": "0",
        },
        "specialCommission": {
            "maker": "0",
            "taker": "0",
            "buyer": "0",
            "seller": "0",
        },
        "discount": {
            "enabledForAccount": True,
            "enabledForSymbol": True,
        },
    }


def test_authoritative_fee_floor_uses_both_sides_without_discount_assumption():
    schedule = authoritative_commission_schedule(commission_payload())
    edge = required_round_trip_edge(
        buy_fee=schedule.maker_buy,
        sell_fee=schedule.maker_sell,
        buy_slippage="0.0001",
        sell_slippage="0.0002",
        safety_margin="0.0001",
        multiplier="3",
    )

    assert schedule.discount_observed is True
    assert schedule.maker_buy == Decimal("0.00075")
    assert edge == Decimal("0.00570")


def test_commission_payload_is_fail_closed_when_a_section_is_missing():
    payload = commission_payload()
    del payload["specialCommission"]

    with pytest.raises(ValueError, match="specialCommission"):
        authoritative_commission_schedule(payload)


def test_inventory_skew_is_exact_and_never_raises_the_hard_cap():
    assert inventory_skew_scale("0", "100", gamma="2") == Decimal("1")
    assert inventory_skew_scale("50", "100", gamma="2") == Decimal("0.75")
    assert inventory_skew_scale("100", "100", gamma="2") == Decimal("0")
    assert inventory_skew_scale("150", "100", gamma="2") == Decimal("0")


def test_vwap_premium_hysteresis_ignores_boundary_noise():
    assert vwap_premium_blocked(
        previously_blocked=False,
        price_to_vwap_ratio="1.0031",
        premium="0.0030",
        hysteresis="0.0002",
    ) is False
    assert vwap_premium_blocked(
        previously_blocked=False,
        price_to_vwap_ratio="1.0033",
        premium="0.0030",
        hysteresis="0.0002",
    ) is True
    assert vwap_premium_blocked(
        previously_blocked=True,
        price_to_vwap_ratio="1.0029",
        premium="0.0030",
        hysteresis="0.0002",
    ) is True
    assert vwap_premium_blocked(
        previously_blocked=True,
        price_to_vwap_ratio="1.0028",
        premium="0.0030",
        hysteresis="0.0002",
    ) is False


def test_regime_gate_blocks_restart_downtrend_and_requires_recovery():
    gate = RegimeExecutionStateMachine(
        confirmations=2,
        recovery_confirmations=2,
        min_hold_sec=0,
    )

    assert gate.policy().buys_allowed is False
    assert gate.update("TREND_DOWN", now=1) == "RECOVERY"
    assert gate.update("TREND_DOWN", now=2) == "TREND_DOWN"
    assert gate.policy().buys_allowed is False
    assert gate.update("RANGE", now=3) == "RECOVERY"
    assert gate.update("RANGE", now=4) == "RANGE"
    assert gate.policy().buys_allowed is True


def test_regime_initial_hold_starts_at_process_creation(monkeypatch):
    monkeypatch.setattr(
        expectancy_controls.time, "monotonic", lambda: 10_000.0
    )
    gate = RegimeExecutionStateMachine(
        confirmations=2,
        recovery_confirmations=2,
        min_hold_sec=300,
    )

    assert gate.update("RANGE", now=10_001) == "RECOVERY"
    assert gate.update("RANGE", now=10_002) == "RECOVERY"
    assert gate.update("RANGE", now=10_299) == "RECOVERY"
    assert gate.update("RANGE", now=10_300) == "RANGE"


def test_panic_blocks_immediately_and_trend_up_reduces_cap():
    gate = RegimeExecutionStateMachine(min_hold_sec=0)
    assert gate.update("RANGE", now=1, panic=True) == "PANIC"
    assert gate.policy().buys_allowed is False

    up = RegimeExecutionStateMachine(
        initial="TREND_UP", min_hold_sec=0
    )
    assert up.policy(trend_up_cap_scale="0.6").cap_scale == Decimal("0.6")
