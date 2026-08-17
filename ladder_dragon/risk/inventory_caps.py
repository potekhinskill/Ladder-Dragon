# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce absolute per-symbol inventory budgets with Decimal arithmetic.

"""Shared exact helpers for the unconditional managed-inventory boundary."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence


D = Decimal
ZERO = D("0")


def finite_non_negative(value: object, *, field: str) -> Decimal:
    """Parse one finite non-negative financial boundary."""
    try:
        result = D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a valid decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return result


def remaining_inventory_budget(
    *,
    hard_cap_quote: object,
    held_base_quantity: object,
    market_price: object,
    open_buy_notional_quote: object,
) -> Decimal:
    """Return capacity after holdings and unfilled BUY commitments."""
    cap = finite_non_negative(hard_cap_quote, field="inventory hard CAP")
    held = finite_non_negative(held_base_quantity, field="held base quantity")
    price = finite_non_negative(market_price, field="inventory market price")
    open_buys = finite_non_negative(
        open_buy_notional_quote, field="open BUY notional"
    )
    return max(ZERO, cap - held * price - open_buys)


def open_buy_notional(orders: Sequence[Mapping[str, object]]) -> Decimal:
    """Value only unfilled quantities from open BUY orders."""
    total = ZERO
    for order in orders:
        if str(order.get("side", "")).upper() != "BUY":
            continue
        price = finite_non_negative(order.get("price", "0"), field="BUY price")
        original = finite_non_negative(
            order.get("origQty", "0"), field="BUY original quantity"
        )
        executed = finite_non_negative(
            order.get("executedQty", "0"), field="BUY executed quantity"
        )
        if executed > original:
            raise ValueError("BUY executed quantity exceeds original quantity")
        total += price * (original - executed)
    return total


def clamp_symbol_order_caps(
    symbols: Sequence[str],
    *,
    safe_order_cap: Decimal,
    allocations: Mapping[str, Decimal],
    exposures: Mapping[str, Decimal],
    hard_caps: Mapping[str, Decimal],
    possible_orders_per_symbol: int,
) -> dict[str, Decimal]:
    """Reserve each inventory remainder across a possible BUY batch."""
    slots = D(str(max(1, int(possible_orders_per_symbol))))
    output: dict[str, Decimal] = {}
    for symbol in symbols:
        hard_cap = hard_caps.get(symbol)
        exposure = exposures.get(symbol, ZERO)
        remaining = (
            max(ZERO, hard_cap - exposure) if hard_cap is not None else ZERO
        )
        output[symbol] = min(
            safe_order_cap,
            allocations.get(symbol, safe_order_cap),
            remaining / slots,
        )
    return output


__all__ = [
    "finite_non_negative",
    "clamp_symbol_order_caps",
    "open_buy_notional",
    "remaining_inventory_budget",
]
