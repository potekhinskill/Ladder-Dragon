# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a VWAP autotune boundary with unchanged tuning behavior.
"""VWAP autotune_math implementation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, Optional


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def fmt_map(data: Dict[str, object], precision: int) -> str:
    return ",".join(f"{sym}:{val:.{precision}f}" for sym, val in sorted(data.items()))


def ema(prev: Optional[float], new: float, alpha: float) -> float:
    if prev is None:
        return new
    return prev * (1.0 - alpha) + new * alpha


def adaptive_discount(
    base: object,
    *,
    pnl: object,
    trade_count: int,
    minimum_trades: int,
    pnl_threshold: object,
    loss_multiplier: object,
    profit_multiplier: object,
    minimum: object,
    maximum: object,
) -> Decimal:
    """Return a bounded VWAP discount from exact performance evidence."""
    try:
        values = tuple(Decimal(str(value)) for value in (
            base, pnl, pnl_threshold, loss_multiplier,
            profit_multiplier, minimum, maximum,
        ))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("VWAP autotune discount inputs must be decimals") from exc
    discount, exact_pnl, threshold, loss_mult, profit_mult, lower, upper = values
    if not all(value.is_finite() for value in values):
        raise ValueError("VWAP autotune discount inputs must be finite")
    if threshold <= 0:
        raise ValueError("VWAP autotune PnL threshold must be positive")
    if discount < 0 or lower < 0 or upper < lower:
        raise ValueError("VWAP autotune discount bounds must be non-negative")
    if upper > Decimal("0.5"):
        raise ValueError("VWAP autotune discount maximum cannot exceed 0.5")
    if loss_mult <= 0 or profit_mult <= 0:
        raise ValueError("VWAP autotune discount multipliers must be positive")
    if int(minimum_trades) < 0 or int(trade_count) < 0:
        raise ValueError("VWAP autotune trade counts must be non-negative")
    if trade_count >= minimum_trades:
        if exact_pnl <= -abs(threshold):
            discount *= loss_mult
        elif exact_pnl >= abs(threshold):
            discount *= profit_mult
    return max(lower, min(upper, discount))


def decimal_ema(previous: object | None, new: Decimal, alpha: object) -> Decimal:
    """Smooth one exact parameter value without binary floating-point arithmetic."""
    try:
        weight = Decimal(str(alpha))
        old = None if previous is None else Decimal(str(previous))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("VWAP discount EMA inputs must be decimals") from exc
    if not weight.is_finite() or not Decimal("0") <= weight <= Decimal("1"):
        raise ValueError("VWAP discount EMA alpha must be in [0, 1]")
    if old is None:
        return new
    if not old.is_finite():
        raise ValueError("VWAP discount EMA history must be finite")
    return old * (Decimal("1") - weight) + new * weight
