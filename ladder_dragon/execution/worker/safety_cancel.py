# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: cancel open BUY exposure without losing partial-fill protection.
"""Shared fail-closed safety cancellation for PANIC and entry vetoes."""

from __future__ import annotations

from decimal import Decimal
import json
import time


def cancel_open_buys(state, symbol: str, order_ids: list[int], *, reason: str) -> list[int]:
    """Cancel BUY exposure and preserve every confirmed partial fill."""
    if reason not in {"panic", "entry-veto"}:
        raise ValueError("unsupported protective BUY cancellation reason")
    remaining = list(order_ids)
    open_states = {"NEW", "PARTIALLY_FILLED", "PENDING_CANCEL"}
    try:
        cancellation_market_price = state.get_price(symbol)
        state._observe_buy_market(symbol, remaining, cancellation_market_price)
    except (
        state.requests.RequestException, RuntimeError, ValueError,
        ArithmeticError, OSError, state.sqlite3.Error,
    ):
        cancellation_market_price = None

    for order_id in list(remaining):
        failure = f"{reason} cancel cannot confirm BUY order {order_id}"
        order = state.require_order_status(
            symbol, order_id, state.get_order, state._trip_execution_halt,
            failure,
        )
        if not order:
            state._trip_execution_halt(
                failure, symbol=symbol, order_id=order_id
            )
            raise RuntimeError(failure)
        side = str(order.get("side") or "BUY").upper()
        status = str(order.get("status") or "").upper()
        original_order = dict(order)
        if side != "BUY":
            continue
        if status in open_states:
            try:
                cancelled = state._signed_request(
                    "DELETE", "/api/v3/order",
                    {"symbol": symbol, "orderId": int(order_id)},
                )
            except (
                state.requests.RequestException, RuntimeError, ValueError,
                ArithmeticError, OSError,
            ) as exc:
                cancelled = state.require_order_status(
                    symbol, order_id, state.get_order,
                    state._trip_execution_halt, failure,
                )
                verified = str(
                    (cancelled or {}).get("status") or ""
                ).upper()
                if verified not in state.TERMINAL_EXCHANGE_STATES:
                    failure = (
                        f"{reason} cancel unconfirmed for BUY order {order_id}"
                    )
                    state._trip_execution_halt(
                        failure, symbol=symbol, order_id=order_id
                    )
                    raise RuntimeError(failure) from exc
            status = str((cancelled or {}).get("status") or "").upper()
            if status not in state.TERMINAL_EXCHANGE_STATES:
                failure = (
                    f"{reason} cancel returned nonterminal state "
                    f"{status or 'UNKNOWN'} for BUY order {order_id}"
                )
                state._trip_execution_halt(
                    failure, symbol=symbol, order_id=order_id
                )
                raise RuntimeError(failure)
            order = cancelled
        if status in state.TERMINAL_EXCHANGE_STATES:
            updated = state._record_order_payload(order)
            if updated is None:
                failure = (
                    f"{reason} cancel cannot update journal for BUY order "
                    f"{order_id}"
                )
                state._trip_execution_halt(
                    failure, symbol=symbol, order_id=order_id
                )
                raise RuntimeError(failure)
            executed_qty = Decimal(str(order.get("executedQty") or "0"))
            state.log(
                f"[SAFETY-CANCEL] {symbol} reason={reason} "
                f"BUY order={order_id} state={updated.state} "
                f"executed={executed_qty}"
            )
            limit_price = Decimal(str(original_order.get("price") or "0"))
            market_price = (
                Decimal(str(cancellation_market_price))
                if cancellation_market_price is not None else None
            )
            created_ms = int(
                original_order.get("time")
                or original_order.get("workingTime")
                or original_order.get("updateTime")
                or int(time.time() * 1000)
            )
            distance_pct = None
            if market_price is not None and market_price > 0 and limit_price > 0:
                distance_pct = (
                    (market_price - limit_price) / market_price * Decimal("100")
                ).quantize(Decimal("0.0001"))
            metadata = dict(updated.metadata or {})
            state.log(
                "[ORDER-LIFETIME] "
                + json.dumps(
                    {
                        "symbol": symbol,
                        "order_id": int(order_id),
                        "cancel_reason": reason,
                        "age_sec": max(
                            0, int((time.time() * 1000 - created_ms) / 1000)
                        ),
                        "ttl_sec": None,
                        "limit_price": str(limit_price),
                        "market_price_at_cancel": (
                            str(market_price)
                            if market_price is not None else None
                        ),
                        "limit_below_market_pct": (
                            str(distance_pct)
                            if distance_pct is not None else None
                        ),
                        "minimum_observed_market_price": metadata.get(
                            "market_min_price"
                        ),
                        "market_observation_count": metadata.get(
                            "market_observation_count", 0
                        ),
                        "executed_qty": str(executed_qty),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            if executed_qty <= 0:
                remaining.remove(order_id)
            continue
        if status == "FILLED":
            continue
        failure = (
            f"{reason} cancel found unsupported state {status or 'UNKNOWN'} "
            f"for BUY order {order_id}"
        )
        state._trip_execution_halt(
            failure, symbol=symbol, order_id=order_id
        )
        raise RuntimeError(failure)
    return remaining


__all__ = ["cancel_open_buys"]
