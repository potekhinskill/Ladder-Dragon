# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the exchange math component of the execution layer.
"""Exact exchange-step arithmetic shared by supervisor and worker."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Mapping


@dataclass(frozen=True)
class ExactSymbolFilters:
    tick: Decimal
    step: Decimal
    minimum_quantity: Decimal
    minimum_notional: Decimal


def exact_symbol_filters(payload: object) -> ExactSymbolFilters | None:
    """Parse the exact fields supplied by the bundled exchange adapter."""
    if not isinstance(payload, Mapping):
        return None
    names = (
        "tickSizeExact",
        "stepSizeExact",
        "minQtyExact",
        "minNotionalExact",
    )
    if any(payload.get(name) in (None, "") for name in names):
        return None
    try:
        values = tuple(Decimal(str(payload[name])) for name in names)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("exchange filters are not exact decimals") from exc
    if any(not value.is_finite() or value <= 0 for value in values):
        raise ValueError("exchange filters must be finite and positive")
    return ExactSymbolFilters(*values)


def decimal(value: object) -> Decimal:
    return Decimal(str(value))


def round_step(value: object, step: object, mode: str = "floor") -> Decimal:
    amount, quantum = decimal(value), decimal(step)
    if quantum <= 0:
        return amount
    rounding = {
        "floor": ROUND_FLOOR,
        "down": ROUND_FLOOR,
        "ceil": ROUND_CEILING,
        "up": ROUND_CEILING,
        "nearest": ROUND_HALF_UP,
    }.get(mode)
    if rounding is None:
        raise ValueError(f"unknown rounding mode: {mode}")
    units = (amount / quantum).to_integral_value(rounding=rounding)
    return units * quantum


def format_step(value: object, step: object) -> str:
    amount, quantum = decimal(value), decimal(step)
    places = max(0, -quantum.normalize().as_tuple().exponent) if quantum > 0 else 8
    return f"{amount:.{places}f}"


def normalized_order_values(
    qty: object,
    price: object,
    *,
    step: object,
    tick: object,
    min_qty: object,
    min_notional: object,
    side: str,
) -> tuple[str, str]:
    step_d, tick_d = decimal(step), decimal(tick)
    qty_d = round_step(qty, step_d, "floor")
    price_d = round_step(price, tick_d, "floor" if side.upper() == "BUY" else "ceil")
    minimum_qty, minimum_notional = decimal(min_qty), decimal(min_notional)
    if qty_d < minimum_qty:
        qty_d = round_step(minimum_qty, step_d, "ceil")
    if price_d > 0 and qty_d * price_d < minimum_notional:
        qty_d = round_step(minimum_notional / price_d, step_d, "ceil")
    if qty_d <= 0 or price_d <= 0:
        raise ValueError(f"invalid normalized order qty={qty_d} price={price_d}")
    return format_step(qty_d, step_d), format_step(price_d, tick_d)
