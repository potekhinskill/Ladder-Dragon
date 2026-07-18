# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Exact exchange-step arithmetic shared by supervisor and worker."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


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
