# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: submit bounded position-flatten slices without overstating progress.

"""Position-flatten slice submission."""

from __future__ import annotations

from decimal import Decimal
from typing import Callable, Mapping

BUY_BLOCKING_MODES = frozenset({
    "reduce_only", "flattening", "flatten_stalled",
})


def _accepted_order(response: object) -> bool:
    return isinstance(response, Mapping) and response.get("orderId") is not None


def submit_flatten_slices(
    *,
    symbol: str,
    remaining: Decimal,
    per_slice: Decimal,
    slice_count: int,
    limit_price: Decimal,
    market_price: Decimal,
    step: object,
    minimum_quantity: object,
    minimum_notional: object,
    market_failover: bool,
    normalize_quantity: Callable[..., Decimal | None],
    place_limit: Callable[..., object],
    place_market: Callable[..., object],
) -> int:
    """Return the number of accepted orders without exceeding the remainder."""
    accepted_count = 0
    attempts = 0
    while remaining > 0 and attempts < max(1, int(slice_count)):
        requested = min(remaining, per_slice)
        quantity = normalize_quantity(
            symbol,
            requested,
            limit_price,
            step,
            minimum_quantity,
            minimum_notional,
        )
        if quantity is None or quantity <= 0 or quantity > remaining:
            break
        response = place_limit(symbol, "SELL", quantity, limit_price)
        accepted = _accepted_order(response)
        accepted_quantity = quantity
        if not accepted and market_failover:
            market_quantity = normalize_quantity(
                symbol,
                quantity,
                market_price,
                step,
                minimum_quantity,
                minimum_notional,
            )
            if (
                market_quantity is not None
                and market_quantity > 0
                and market_quantity <= remaining
            ):
                response = place_market(
                    symbol,
                    "SELL",
                    market_quantity,
                    ref_price=market_price,
                )
                accepted = _accepted_order(response)
                accepted_quantity = market_quantity
        attempts += 1
        if not accepted:
            break
        remaining -= accepted_quantity
        accepted_count += 1
    return accepted_count
