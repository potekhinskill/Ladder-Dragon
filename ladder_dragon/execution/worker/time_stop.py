# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: apply the maximum holding-time safety policy.

"""Maximum holding-time enforcement."""

from __future__ import annotations

from typing import Any


def apply_time_stop(context: Any) -> None:
    """Flatten expired tracked fills and trip the execution halt."""
    state = context.state
    max_hold_min = max(
        0.0,
        state.getenv_float("BOT_MAX_HOLDING_MINUTES", 0.0),
    )
    if not (
        state.LIVE_MODE and max_hold_min > 0 and context.placed_ids
    ):
        return
    now_ms = int(state.time.time() * 1000)
    for order_id in list(context.placed_ids):
        try:
            held = state.get_order(context.symbol, order_id)
        except (
            state.requests.RequestException,
            RuntimeError,
            ValueError,
            ArithmeticError,
            OSError,
        ) as exc:
            reason = f"time stop cannot confirm BUY order {order_id}"
            state._trip_execution_halt(
                reason,
                symbol=context.symbol,
                order_id=order_id,
                error_type=type(exc).__name__,
            )
            # Keep the complete queue. Protection can retry after recovery.
            return
        if not held or str(held.get("status", "")).upper() != "FILLED":
            continue
        opened_ms = int(
            held.get("time") or held.get("transactTime") or now_ms
        )
        if now_ms - opened_ms < max_hold_min * 60_000:
            continue
        qty_exp = state.Decimal(str(held.get("executedQty", 0) or 0))
        if state.STATS_CON is not None:
            try:
                lots = state.oldest_lots(
                    state.STATS_CON,
                    context.symbol,
                )
                lot_qty = sum(
                    (lot.qty for lot in lots),
                    state.Decimal("0"),
                )
                if lot_qty > 0:
                    qty_exp = min(qty_exp, lot_qty)
            except state.sqlite3.Error as exc:
                state.dbg(
                    "[TIME-STOP] FIFO lots unavailable="
                    f"{type(exc).__name__}"
                )
        if qty_exp > 0:
            state.log(
                f"[TIME-STOP] {context.symbol} order={order_id} "
                f"age>{max_hold_min:g}m; flattening"
            )
            state.place_market_order(
                context.symbol,
                "SELL",
                qty_exp,
                ref_price=state.get_price_exact(context.symbol),
                filters=state.symbol_filters.get(context.symbol),
            )
        state._trip_execution_halt(
            "max holding time exceeded",
            symbol=context.symbol,
            order_id=order_id,
        )
        context.placed_ids.remove(order_id)
