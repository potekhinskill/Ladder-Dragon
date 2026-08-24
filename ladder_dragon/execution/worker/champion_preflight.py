# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify an immutable CHAMPION before LIVE worker exchange access.
"""Fail-closed worker preflight for the active CHAMPION identity."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping


def _nonnegative_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must be non-negative")
    return parsed


def require_live_champion(state: object, args: object) -> dict[str, object]:
    """Load the exact policy and enforce it before exchange access."""
    from ladder_dragon.strategy.prediction.champion_registry import (
        verify_active_champion,
    )
    from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore

    prediction_db = state.os.getenv("PREDICTION_SHADOW_DB", "").strip()
    activation_id = state.os.getenv("BOT_CHAMPION_ACTIVATION_ID", "").strip()
    champion_fingerprint = state.os.getenv(
        "BOT_CHAMPION_FINGERPRINT", ""
    ).strip()
    policy_fingerprint = state.os.getenv(
        "BOT_CHAMPION_POLICY_FINGERPRINT", ""
    ).strip()
    if not all(
        (prediction_db, activation_id, champion_fingerprint, policy_fingerprint)
    ):
        raise ValueError("LIVE worker requires an active CHAMPION identity")
    champion = verify_active_champion(
        PredictionShadowStore(prediction_db),
        symbol=args.symbol,
        activation_id=activation_id,
        champion_fingerprint=champion_fingerprint,
        execution_policy_fingerprint=policy_fingerprint,
    )
    policy = champion.get("execution_policy")
    if not isinstance(policy, Mapping):
        raise ValueError("active CHAMPION execution policy is unavailable")
    if state.os.getenv("BOT_CHAMPION_PROBATION_ALLOWED", "") != "YES":
        raise ValueError("LIVE worker requires a current CHAMPION probation gate")
    order_maximum = _nonnegative_decimal(
        policy.get("maximum_order_notional_usdt"), field="CHAMPION order CAP"
    )
    inventory_maximum = _nonnegative_decimal(
        policy.get("maximum_inventory_usdt"), field="CHAMPION inventory CAP"
    )
    cap_name = "BOT_CAP_PER_ORDER"
    configured_order = state.os.getenv(cap_name, "").strip()
    order_cap = (
        _nonnegative_decimal(configured_order, field=cap_name)
        if configured_order else order_maximum
    )
    inventory_name = f"RISK_MANAGED_INVENTORY_HARD_CAP_{args.symbol.upper()}"
    configured_inventory = state.os.getenv(inventory_name, "").strip()
    inventory_cap = (
        _nonnegative_decimal(configured_inventory, field=inventory_name)
        if configured_inventory else inventory_maximum
    )
    state.os.environ[cap_name] = format(min(order_cap, order_maximum), "f")
    state.os.environ[inventory_name] = format(
        min(inventory_cap, inventory_maximum), "f"
    )

    # Direct worker startup cannot replace immutable policy values from CLI.
    target = _nonnegative_decimal(
        policy.get("target_return"), field="CHAMPION target return"
    )
    stop = _nonnegative_decimal(
        policy.get("stop_limit_distance"), field="CHAMPION stop limit distance"
    )
    stop_offset = _nonnegative_decimal(
        policy.get("stop_trigger_offset_pct"), field="CHAMPION stop trigger offset"
    )
    maximum_holding = int(policy.get("maximum_holding_min") or 0)
    if stop_offset <= 0 or stop_offset >= stop or maximum_holding <= 0:
        raise ValueError("CHAMPION protective timing is invalid")
    args.tp1 = state._compat_float(target)
    args.tp2 = state._compat_float(target)
    args.sl = state._compat_float(-stop)
    args.stop_limit_offset_pct = state._compat_float(stop_offset)
    state.os.environ["BOT_MAX_HOLDING_MINUTES"] = str(maximum_holding)
    args.target_buy_per_symbol = 1
    args.buy_limit_maker = True
    args.sell_limit_maker = True
    args.bear_buy_shift_pct = 0.0
    if args.bear_cap_scale is not None:
        args.bear_cap_scale = min(1.0, state._compat_float(args.bear_cap_scale))
    args.buy_vwap_discount = None
    args.buy_vwap_discount_scale = None
    return champion


def champion_ladder(
    state: object,
    champion: Mapping[str, object],
    current_price: object,
) -> list[float]:
    """Reconstruct entry and protective anchors from immutable semantics."""
    policy = champion.get("execution_policy")
    if not isinstance(policy, Mapping):
        raise ValueError("active CHAMPION execution policy is unavailable")
    market = _nonnegative_decimal(current_price, field="current market price")
    if market <= 0:
        raise ValueError("current market price must be positive")
    gap = _nonnegative_decimal(
        policy.get("entry_gap_bps"), field="CHAMPION entry gap"
    ) / Decimal("10000")
    target = _nonnegative_decimal(
        policy.get("target_return"), field="CHAMPION target return"
    )
    stop = _nonnegative_decimal(
        policy.get("stop_limit_distance"), field="CHAMPION stop limit distance"
    )
    if gap >= 1 or stop >= 1:
        raise ValueError("CHAMPION price distance is invalid")
    entry = market * (Decimal("1") - gap)
    anchors = (
        entry * (Decimal("1") - stop),
        entry,
        entry * (Decimal("1") + target),
    )
    # Float conversion occurs only at the legacy CLI ladder boundary.
    return [state._compat_float(value) for value in anchors]


__all__ = ["champion_ladder", "require_live_champion"]
