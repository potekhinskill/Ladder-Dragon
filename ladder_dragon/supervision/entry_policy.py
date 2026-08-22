# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: calculate pure Decimal entry policies for the supervisor.
"""Pure Decimal policies for adaptive supervisor entry planning."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def finite_decimal(value: object, *, name: str) -> Decimal:
    """Parse an exact finite decimal at a financial decision boundary."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def directional_entry_settings(
    *,
    base_gap: object,
    atr_pct: object,
    base_min_profit: object,
    auto_adapt: bool,
    gap_atr_coefficient: object,
    profit_atr_coefficient: object,
    gap_floor: object,
    gap_ceiling: object,
    mode: str,
    up_gap_multiplier: object,
    down_gap_multiplier: object,
    take_profit_pct: object,
    up_tp_multiplier: object,
    down_tp_multiplier: object,
    tp_floor: object,
    tp_ceiling: object,
    allow_observation_clamp: bool = False,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return exact entry gap, profit floor and TP for one market regime."""
    gap = finite_decimal(base_gap, name="base BUY gap")
    volatility = finite_decimal(atr_pct, name="ATR percentage")
    minimum_profit = finite_decimal(base_min_profit, name="minimum profit")
    floor = finite_decimal(gap_floor, name="BUY gap floor")
    ceiling = finite_decimal(gap_ceiling, name="BUY gap ceiling")
    tp = finite_decimal(take_profit_pct, name="take profit")
    tp_minimum = finite_decimal(tp_floor, name="take profit floor")
    tp_maximum = finite_decimal(tp_ceiling, name="take profit ceiling")
    gap_atr = finite_decimal(gap_atr_coefficient, name="BUY ATR coefficient")
    profit_atr = finite_decimal(
        profit_atr_coefficient,
        name="profit ATR coefficient",
    )
    up_gap = finite_decimal(up_gap_multiplier, name="UP BUY gap multiplier")
    down_gap = finite_decimal(
        down_gap_multiplier,
        name="DOWN BUY gap multiplier",
    )
    up_tp = finite_decimal(up_tp_multiplier, name="UP TP multiplier")
    down_tp = finite_decimal(down_tp_multiplier, name="DOWN TP multiplier")
    if (
        min(gap, minimum_profit, floor, volatility) < 0
        or ceiling <= 0
        or floor > ceiling
        or tp_minimum <= 0
        or tp_minimum > tp_maximum
        or min(gap_atr, profit_atr, up_gap, down_gap, up_tp, down_tp) <= 0
    ):
        raise ValueError("directional entry bounds are invalid")
    if auto_adapt:
        gap = max(gap, gap_atr * volatility, floor)
        minimum_profit = max(
            minimum_profit,
            profit_atr * volatility,
            floor * Decimal("0.8"),
        )
    normalized_mode = str(mode).upper()
    if normalized_mode == "UP":
        gap *= up_gap
        tp *= up_tp
    elif normalized_mode == "DOWN":
        gap *= down_gap
        tp *= down_tp
    gap = min(ceiling, max(floor, gap))
    required_tp = max(tp_minimum, tp, minimum_profit)
    if required_tp > tp_maximum:
        if not allow_observation_clamp:
            raise ValueError(
                "minimum profitable TP exceeds the configured ceiling"
            )
        # SHADOW retains the configured plan for observation. Execution uses
        # the default fail-closed branch for the same inconsistent bounds.
        required_tp = tp_maximum
    return gap, minimum_profit, required_tp


def adaptive_best_buy_price(
    market_price: object,
    entry_gap: object,
) -> Decimal:
    """Return a strictly positive, below-market adaptive BUY price."""
    market = finite_decimal(market_price, name="current entry price")
    gap = finite_decimal(entry_gap, name="adaptive BUY gap")
    if market <= 0 or gap <= 0 or gap >= 1:
        raise ValueError("adaptive BUY inputs are invalid")
    price = market * (Decimal("1") - gap)
    if price <= 0 or price >= market:
        raise ValueError("adaptive BUY must remain strictly below market")
    return price
