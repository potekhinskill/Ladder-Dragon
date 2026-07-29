# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reconcile fills and protection without creating new BUY exposure.

"""Worker event-loop service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkerLoopContext:
    """Carry explicit mutable state used by the non-buying worker loop."""

    state: Any
    args: Any
    symbol: str
    attach_oco: bool
    ladder_prices: list[float]
    placed_ids: list[int]
    panic_active: bool
    panic_sell_floor_pct: Any
    breakeven: Any
    breakeven_state: Any
    user_stream_mailbox: Any
    user_stream_observer: Any
    started_at: float
    protection_state: str


def _status_message(context: WorkerLoopContext, left: int) -> str:
    state = context.state
    return (
        f"[status] {context.symbol} pid={state.os.getpid()} "
        f"OCO:{context.protection_state} | "
        f"started:{state.datetime.fromtimestamp(context.started_at).strftime('%Y-%m-%d %H:%M:%S')} | "
        f"left:{int(left)}s | last: idle"
    )


def _record_stream_events(
    context: WorkerLoopContext,
    stream_events: list[Any],
) -> None:
    """Persist sanitized event latency outside the order mutation path."""
    state = context.state
    journal = state._order_journal()
    latency_path = state.os.getenv(
        "BOT_EXECUTION_LATENCY_LOG",
        str(
            state.Path(state.__file__).resolve().parents[3]
            / "logs"
            / "execution_latency.ndjson"
        ),
    )
    if journal is None:
        return
    for event in stream_events:
        created_ms = journal.created_at_ms_for_exchange_order(event.order_id)
        if created_ms is None:
            continue
        try:
            commission_quote = None
            commission_status = "not_applicable"
            if event.execution_type == "TRADE":
                commission_amount = state.Decimal(event.commission_amount)
                if commission_amount == 0:
                    commission_quote = state.Decimal("0")
                    commission_status = "exact"
                else:
                    commission_quote, commission_status = (
                        state._commission_quote_value(
                            event.symbol,
                            event.commission_asset,
                            commission_amount,
                            state.Decimal(event.last_price),
                            event.transaction_time_ms,
                        )
                    )
            state.append_execution_latency_sample(
                latency_path,
                event,
                intent_created_at_ms=created_ms,
                commission_quote=commission_quote,
                commission_value_status=commission_status,
            )
        except (ArithmeticError, OSError, TypeError, ValueError) as exc:
            state.dbg(
                "[USER-STREAM] execution latency sample "
                f"unavailable={type(exc).__name__}"
            )


def _reconcile_tracked_buys(
    context: WorkerLoopContext,
    *,
    event_woken: bool,
) -> None:
    """Run authoritative protection immediately after a stream wakeup."""
    state = context.state
    args = context.args
    trace = state.LatencyTrace(context.symbol, "fill-reconcile")
    if event_woken:
        trace.mark("fill_received")
    pending_before = list(context.placed_ids)
    terminal_unfilled: set[int] = set()
    context.placed_ids = state.protect_filled_buys(
        context.symbol,
        context.placed_ids,
        context.ladder_prices,
        config=state.ProtectionConfig(
            stop_limit_offset_pct=args.stop_limit_offset_pct,
            oco_fallback=args.oco_fallback,
            sell_limit_maker=args.sell_limit_maker,
            avg_cache_ttl=args.avg_cache_ttl,
            avg_lookback=args.avg_lookback,
            panic_sell_floor_pct=context.panic_sell_floor_pct,
        ),
        panic_active=context.panic_active,
        breakeven_enabled=context.breakeven.enabled,
        state_store=context.breakeven_state,
        dependencies=state._protection_dependencies(),
        terminal_unfilled_order_ids=terminal_unfilled,
    )
    if context.user_stream_observer is not None:
        context.user_stream_observer.record_rest_reconciliation(
            event_woken=event_woken
        )
    context.protection_state = state._protection_state_after_sweep(
        pending_before,
        context.placed_ids,
        terminal_unfilled,
    )
    if event_woken and context.protection_state == "confirmed":
        trace.mark("protection_active")
    if not event_woken:
        return
    try:
        trace.append(
            state.os.getenv(
                "BOT_LATENCY_TRACE_LOG",
                str(
                    state.Path(state.__file__).resolve().parents[3]
                    / "logs"
                    / "latency_trace.ndjson"
                ),
            )
        )
    except OSError as exc:
        state.dbg(f"[LATENCY] trace unavailable={type(exc).__name__}")


def _refresh_panic_state(context: WorkerLoopContext) -> bool:
    """Refresh runtime PANIC state and fail closed on unavailable evidence."""
    state = context.state
    args = context.args
    try:
        ema20, atr, prev_close = state.get_indicators_cached(
            context.symbol,
            args.panic_interval,
            ttl_sec=20,
        )
        avg_px = state.avg_entry(
            context.symbol,
            cache_ttl=args.avg_cache_ttl,
            lookback=args.avg_lookback,
        )
        runtime_price = state.get_price(context.symbol)
        state._observe_buy_market(
            context.symbol,
            context.placed_ids,
            runtime_price,
        )
        panic_active, _ = state._panic_state_fail_closed(
            "panic-runtime",
            context.symbol,
            lambda: state.update_panic_state(
                symbol=context.symbol,
                now_px=runtime_price,
                ema20=ema20,
                atr=atr,
                prev_close=prev_close,
                avg_entry_px=avg_px,
                panic_drop_pct=state._compat_float(args.panic_drop_pct),
                panic_k_atr=state._compat_float(args.panic_k_atr),
                debounce_checks=int(args.panic_debounce_checks),
                cooldown_sec=int(args.panic_cooldown_sec),
            ),
        )
        return panic_active
    except (
        state.requests.RequestException,
        RuntimeError,
        ValueError,
        ArithmeticError,
        OSError,
        state.sqlite3.Error,
    ) as exc:
        state._record_safety_control_failure(
            "panic-runtime",
            context.symbol,
            exc,
        )
        return True


def _run_gap_watchdog(context: WorkerLoopContext) -> None:
    """Keep protection gap checks fail closed during the runtime loop."""
    state = context.state
    if not (
        state.LIVE_MODE
        and state.os.getenv("BOT_GAP_WATCHDOG", "1").lower()
        in ("1", "true", "yes")
    ):
        return
    try:
        gap_price = state.get_price(context.symbol)
    except (
        state.requests.RequestException,
        RuntimeError,
        ValueError,
        ArithmeticError,
        OSError,
    ) as exc:
        state._record_safety_control_failure(
            "gap-watchdog",
            context.symbol,
            exc,
        )
        return
    state._gap_watchdog_fail_closed(
        context.symbol,
        gap_price,
        dependencies=state._protection_dependencies(),
        gap_tolerance_pct=max(
            0.0,
            state.getenv_float("BOT_GAP_TOLERANCE_PCT", 0.001),
        ),
    )


def _apply_time_stop(context: WorkerLoopContext) -> None:
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
        held = state.get_order(context.symbol, order_id)
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


def run_event_loop(context: WorkerLoopContext) -> None:
    """Observe tracked orders and maintain protection without creating BUYs."""
    state = context.state
    args = context.args
    try:
        state.sync_account_trades(
            context.symbol,
            runtime=state.namespace(),
        )
    except (
        state.requests.RequestException,
        RuntimeError,
        ValueError,
        ArithmeticError,
        OSError,
        state.sqlite3.Error,
    ) as exc:
        state.log(f"[STATS] poll error: {exc}")

    last_check = 0
    panic_cancel_applied = False
    for left in state.trading_wakeups(
        int(args.loop_minutes * 60),
        running=lambda: state.RUN,
        wait=lambda timeout: (
            context.user_stream_mailbox.wait_for(
                context.placed_ids,
                timeout,
            )
            if (
                context.user_stream_observer is not None
                and context.placed_ids
            )
            else state.time.sleep(timeout)
        ),
    ):
        stream_events = (
            context.user_stream_mailbox.consume_for(context.placed_ids)
            if context.attach_oco and context.placed_ids
            else []
        )
        if stream_events:
            latest = stream_events[-1]
            state.log(
                f"[USER-STREAM] {context.symbol} order={latest.order_id} "
                f"event={latest.execution_type}/{latest.order_status}; "
                "immediate authoritative REST reconciliation"
            )
            _reconcile_tracked_buys(context, event_woken=True)
            _record_stream_events(context, stream_events)
            last_check = 0

        if state.status_due(left, args.status_interval):
            state.log(_status_message(context, left))

        previous_panic_active = context.panic_active
        context.panic_active = _refresh_panic_state(context)
        if not context.panic_active:
            panic_cancel_applied = False
        elif (
            state.LIVE_MODE
            and not panic_cancel_applied
            and context.placed_ids
        ):
            context.placed_ids = state.cancel_open_buys_for_panic(
                context.symbol,
                context.placed_ids,
            )
            panic_cancel_applied = True
            if not context.placed_ids:
                context.protection_state = "not_needed"

        _run_gap_watchdog(context)

        if state._panic_recovery_restart_required(
            live_mode=state.LIVE_MODE,
            was_active=previous_panic_active,
            is_active=context.panic_active,
            tracked_buy_order_ids=context.placed_ids,
        ):
            state.log(
                f"[PANIC-RECOVERY] {context.symbol} no tracked BUY; "
                "requesting fresh gated executor cycle"
            )
            return

        if (
            context.attach_oco
            and context.placed_ids
            and not stream_events
        ):
            last_check += 1
            if state.reconciliation_due(
                last_check,
                args.check_fills_interval,
                (),
            ):
                last_check = 0
                _reconcile_tracked_buys(context, event_woken=False)

        _apply_time_stop(context)

        if context.breakeven.due():
            state.maintain_breakeven(
                context.symbol,
                offset_pct=context.breakeven.offset_pct,
                stop_limit_offset_pct=args.stop_limit_offset_pct,
                state_store=context.breakeven_state,
                dependencies=state._protection_dependencies(),
            )
