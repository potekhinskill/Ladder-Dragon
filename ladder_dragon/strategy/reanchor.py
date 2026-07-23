# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: plan bounded, fail-closed BUY re-anchors without touching SELL protection.
"""Exact planning for bounded adaptive BUY re-anchors."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

from ladder_dragon.execution.exchange_math import round_step


ZERO = Decimal("0")


@dataclass(frozen=True)
class BuyReanchor:
    """A safe cancellation and bounded replacement target for one BUY."""

    order_id: int
    old_price: Decimal
    target_price: Decimal
    age_sec: int


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def plan_buy_reanchors(
    orders: Iterable[Mapping[str, object]],
    ladder_prices: Sequence[object],
    *,
    now_price: object,
    tick_size: object,
    now_ms: int,
    min_age_sec: int,
    trigger_pct: object,
    max_step_pct: object,
    max_per_cycle: int,
    max_market_gap_pct: object | None = None,
) -> list[BuyReanchor]:
    """Return BUY-only re-anchors ranked against the current ladder.

    Existing BUYs and desired BUY levels are compared best-price first. A
    partially filled order retains its rank but is never canceled. Replacement
    movement is capped per cycle and rounded down to the venue tick so a rapid
    move cannot turn one refresh into an unbounded market chase.
    """

    market = _decimal(now_price, field="now_price")
    tick = _decimal(tick_size, field="tick_size")
    trigger = _decimal(trigger_pct, field="trigger_pct")
    max_step = _decimal(max_step_pct, field="max_step_pct")
    max_market_gap = (
        _decimal(max_market_gap_pct, field="max_market_gap_pct")
        if max_market_gap_pct is not None
        else None
    )
    if market <= ZERO or tick <= ZERO:
        raise ValueError("now_price and tick_size must be positive")
    if min_age_sec < 0 or max_per_cycle < 0:
        raise ValueError("re-anchor age and count must be non-negative")
    if not ZERO < trigger < Decimal("0.25"):
        raise ValueError("trigger_pct must be in (0, 0.25)")
    if not ZERO < max_step < Decimal("0.25"):
        raise ValueError("max_step_pct must be in (0, 0.25)")
    if (
        max_market_gap is not None
        and not ZERO < max_market_gap < Decimal("0.25")
    ):
        raise ValueError("max_market_gap_pct must be in (0, 0.25)")

    desired = sorted(
        {
            round_step(_decimal(value, field="ladder_price"), tick, "floor")
            for value in ladder_prices
            if ZERO < _decimal(value, field="ladder_price") < market
        },
        reverse=True,
    )
    if not desired or max_per_cycle == 0:
        return []
    if max_market_gap is not None:
        near_market = round_step(
            market * (Decimal("1") - max_market_gap),
            tick,
            "floor",
        )
        if ZERO < near_market < market:
            # Only the best BUY is pulled toward the market. Deeper ladder
            # levels keep their original spacing, while the per-cycle step,
            # age and trigger limits still prevent an unbounded chase.
            desired[0] = max(desired[0], near_market)

    ranked_orders: list[tuple[Decimal, int, int, Decimal]] = []
    for order in orders:
        if str(order.get("side", "")).upper() != "BUY":
            continue
        if str(order.get("type", "")).upper() not in {"LIMIT", "LIMIT_MAKER"}:
            continue
        try:
            order_id = int(order.get("orderId") or 0)
            price = _decimal(order.get("price") or "0", field="order.price")
            executed = _decimal(
                order.get("executedQty") or "0", field="order.executedQty"
            )
            update_ms = int(order.get("updateTime") or order.get("time") or 0)
        except (TypeError, ValueError):
            continue
        if order_id <= 0 or price <= ZERO or executed < ZERO or update_ms <= 0:
            continue
        age_sec = max(0, (int(now_ms) - update_ms) // 1000)
        ranked_orders.append((price, order_id, age_sec, executed))

    ranked_orders.sort(key=lambda row: row[0], reverse=True)
    planned: list[BuyReanchor] = []
    for rank, (old_price, order_id, age_sec, executed) in enumerate(ranked_orders):
        if rank >= len(desired):
            break
        desired_price = desired[rank]
        if executed > ZERO or age_sec < min_age_sec:
            continue
        if desired_price <= old_price * (Decimal("1") + trigger):
            continue
        bounded = min(
            desired_price,
            old_price * (Decimal("1") + max_step),
        )
        target = round_step(bounded, tick, "floor")
        if target <= old_price or target >= market:
            continue
        planned.append(
            BuyReanchor(
                order_id=order_id,
                old_price=old_price,
                target_price=target,
                age_sec=age_sec,
            )
        )
        if len(planned) >= max_per_cycle:
            break
    return planned
