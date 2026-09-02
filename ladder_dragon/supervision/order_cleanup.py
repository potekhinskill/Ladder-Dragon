# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: cancel only stale, unfilled BUY orders under bounded cleanup rules.
"""Supervisor order-cleanup policy."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any, Mapping, Sequence


def _log_order_lifetime(
    symbol: str,
    order: Mapping[str, Any],
    *,
    now_price: float,
    age_sec: int,
    ttl_sec: int | None,
    cancel_reason: str,
    runtime: Mapping[str, Any],
) -> None:
    """Emit secret-free evidence explaining one unfilled cancellation."""
    order_id = int(order.get("orderId") or 0)
    observation = runtime["read_order_observation"](
        os.getenv("BOT_ORDER_JOURNAL", ""), order_id
    )
    limit_price = runtime["money"](order.get("price") or "0")
    market_price = runtime["money"](now_price)
    distance_pct = None
    if market_price > 0 and limit_price > 0:
        distance_pct = (
            (market_price - limit_price) / market_price * Decimal("100")
        ).quantize(Decimal("0.0001"))
    runtime["log"](
        "[ORDER-LIFETIME] "
        + json.dumps(
            {
                "symbol": symbol,
                "order_id": order_id,
                "cancel_reason": cancel_reason,
                "age_sec": max(0, int(age_sec)),
                "ttl_sec": int(ttl_sec) if ttl_sec is not None else None,
                "limit_price": str(limit_price),
                "market_price_at_cancel": str(market_price),
                "limit_below_market_pct": (
                    str(distance_pct) if distance_pct is not None else None
                ),
                "minimum_observed_market_price": observation.get(
                    "market_min_price"
                ),
                "market_observation_count": observation.get(
                    "market_observation_count", 0
                ),
                "executed_qty": str(order.get("executedQty") or "0"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def startup_cleanup_orders(
    symbol: str,
    now_price: float,
    ladder_prices: Sequence[float],
    tick_size: float,
    grace_sec: int | None,
    *,
    runtime: Mapping[str, Any],
    orders: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Cancel only proven stale startup BUYs while preserving every SELL."""
    operation_errors = runtime["SUPERVISOR_OPERATION_ERRORS"]
    try:
        orders = runtime["list_open_orders"](symbol) if orders is None else orders
    except operation_errors as exc:
        runtime["log"](f"[START-CLEANUP] {symbol} list_open_orders failed: {exc}")
        return {"reviewed": 0, "canceled": 0}
    if not orders:
        return {"reviewed": 0, "canceled": 0}

    rounded = runtime["_round_to_tick"]
    allowed = {rounded(price, tick_size) for price in ladder_prices}
    now_ms = int(time.time() * 1000)
    reviewed = canceled = 0
    for order in orders:
        try:
            reviewed += 1
            # Generic cleanup never owns protective SELL, OCO, or OTOCO legs.
            if str(order.get("side") or "").upper() != "BUY":
                continue
            if str(order.get("type") or "").upper() not in (
                "LIMIT",
                "LIMIT_MAKER",
            ):
                continue
            price = runtime["_analytics_float"](order.get("price") or 0.0)
            rounded_price = rounded(price, tick_size)
            updated = int(order.get("updateTime") or order.get("time") or now_ms)
            age = max(0, (now_ms - updated) // 1000)
            off_ladder = rounded_price not in allowed
            old = grace_sec is not None and age > int(grace_sec)
            off_ladder_grace = int(
                os.getenv(
                    "START_CLEANUP_OFFLADDER_GRACE_SEC",
                    str(grace_sec if grace_sec is not None else 900),
                )
                or 0
            )
            reason = f"age>{grace_sec}s" if old else None
            if reason is None and off_ladder:
                if off_ladder_grace == 0 or age > off_ladder_grace:
                    reason = "off-ladder"
            if reason and runtime["cancel_order"](
                symbol, int(order.get("orderId"))
            ):
                canceled += 1
                runtime["log"](
                    f"[START-CLEANUP] {symbol} canceled id={order.get('orderId')} "
                    f"price={rounded_price} age={age}s ttl={grace_sec}s "
                    f"reason={reason}"
                )
                _log_order_lifetime(
                    symbol,
                    order,
                    now_price=now_price,
                    age_sec=age,
                    ttl_sec=grace_sec,
                    cancel_reason=reason,
                    runtime=runtime,
                )
        except operation_errors as exc:
            runtime["log"](f"[START-CLEANUP] {symbol} skip: {exc}")
    runtime["log"](
        f"[START-CLEANUP-SUM] {symbol} reviewed={reviewed} canceled={canceled}"
    )
    return {"reviewed": reviewed, "canceled": canceled}


def smart_cleanup_orders(
    symbol: str,
    now_price: float,
    ladder_prices: Sequence[float],
    tick_size: float,
    near_ttl_sec: int | None,
    far_ttl_sec: int | None,
    cancel_offladder: bool = True,
    *,
    runtime: Mapping[str, Any],
    orders: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Apply bounded TTL cleanup without touching protective orders."""
    operation_errors = runtime["SUPERVISOR_OPERATION_ERRORS"]
    try:
        orders = runtime["list_open_orders"](symbol) if orders is None else orders
    except operation_errors as exc:
        runtime["log"](f"[CLEANUP] {symbol} list_open_orders failed: {exc}")
        return {"reviewed": 0, "canceled": 0}
    if not orders:
        return {"reviewed": 0, "canceled": 0}

    now_ms = int(time.time() * 1000)
    near_low = now_price * 0.90
    near_high = now_price * 1.10
    rounded = runtime["_round_to_tick"]
    allowed = (
        {rounded(price, tick_size) for price in ladder_prices}
        if cancel_offladder
        else set()
    )
    off_ladder_grace = int(
        os.getenv(
            "CLEANUP_OFFLADDER_GRACE_SEC",
            str(runtime["CLEANUP_WARMUP_SEC"]),
        )
        or 0
    )
    reviewed = canceled = 0
    for order in orders:
        try:
            reviewed += 1
            # A SELL can be the only active protection for filled inventory.
            if str(order.get("side") or "").upper() != "BUY":
                continue
            price = runtime["_analytics_float"](order.get("price") or 0.0)
            rounded_price = rounded(price, tick_size)
            updated = int(order.get("updateTime") or order.get("time") or now_ms)
            age = max(0, (now_ms - updated) // 1000)
            ttl = near_ttl_sec if near_low <= price <= near_high else far_ttl_sec
            reason = f"age>{ttl}s" if ttl and age > ttl else None
            if (
                reason is None
                and cancel_offladder
                and rounded_price not in allowed
                and age > off_ladder_grace
            ):
                reason = "off-ladder"
            if reason and runtime["cancel_order"](
                symbol, int(order.get("orderId"))
            ):
                canceled += 1
                runtime["log"](
                    f"[CLEANUP] {symbol} canceled {order.get('side')} "
                    f"{order.get('type')} id={order.get('orderId')} "
                    f"price={rounded_price} age={age}s reason={reason}"
                )
                _log_order_lifetime(
                    symbol,
                    order,
                    now_price=now_price,
                    age_sec=age,
                    ttl_sec=ttl,
                    cancel_reason=reason,
                    runtime=runtime,
                )
        except operation_errors as exc:
            runtime["log"](f"[CLEANUP] {symbol} skip: {exc}")
    runtime["log"](
        f"[CLEANUP-SUM] {symbol} reviewed={reviewed} canceled={canceled}"
    )
    return {"reviewed": reviewed, "canceled": canceled}


def initial_cleanup_orders(
    symbol: str,
    now_price: float,
    ladder_prices: Sequence[float],
    tick_size: float,
    grace_sec: int | None,
    near_ttl_sec: int | None,
    far_ttl_sec: int | None,
    *,
    runtime: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    """Apply both initial policies to one authoritative open-order snapshot."""
    operation_errors = runtime["SUPERVISOR_OPERATION_ERRORS"]
    try:
        orders = runtime["list_open_orders"](symbol)
    except operation_errors as exc:
        runtime["log"](f"[INITIAL-CLEANUP] {symbol} list_open_orders failed: {exc}")
        empty = {"reviewed": 0, "canceled": 0}
        return {"startup": dict(empty), "periodic": dict(empty)}
    handled_ids: set[int] = set()
    startup_runtime = dict(runtime)
    cancel_order = runtime["cancel_order"]

    def tracked_cancel(target_symbol: str, order_id: int) -> bool:
        handled_ids.add(int(order_id))
        return bool(cancel_order(target_symbol, order_id))

    startup_runtime["cancel_order"] = tracked_cancel
    startup = startup_cleanup_orders(
        symbol, now_price, ladder_prices, tick_size, grace_sec,
        runtime=startup_runtime, orders=orders,
    )
    remaining = [
        order for order in orders
        if int(order.get("orderId") or 0) not in handled_ids
    ]
    periodic = smart_cleanup_orders(
        symbol, now_price, ladder_prices, tick_size, near_ttl_sec, far_ttl_sec,
        runtime=runtime, orders=remaining,
    )
    return {"startup": startup, "periodic": periodic}


__all__ = [
    "initial_cleanup_orders",
    "smart_cleanup_orders",
    "startup_cleanup_orders",
]
