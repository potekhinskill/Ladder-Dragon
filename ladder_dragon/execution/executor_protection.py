# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor protection component of the execution layer.
"""Ladder Dragon executor protection support."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, MutableSet, Optional, Sequence

import requests

from ladder_dragon.execution.order_recovery import OrderJournal, TERMINAL_EXCHANGE_STATES
from ladder_dragon.execution.exchange_math import exact_symbol_filters, round_step


_PROTECTION_DATA_ERRORS = (
    ArithmeticError,
    OSError,
    RuntimeError,
    sqlite3.Error,
    TypeError,
    ValueError,
    requests.RequestException,
)


@dataclass(frozen=True)
class ProtectionConfig:
    """Represent ProtectionConfig."""

    stop_limit_offset_pct: float
    oco_fallback: str
    sell_limit_maker: bool
    avg_cache_ttl: int
    avg_lookback: int
    panic_sell_floor_pct: Optional[float]


@dataclass
class BreakevenRuntime:
    """Represent BreakevenRuntime."""

    enabled: bool
    offset_pct: float
    check_interval: int
    tick: int = 0

    def due(self) -> bool:
        if not self.enabled:
            return False
        self.tick += 1
        if self.tick < max(1, int(self.check_interval)):
            return False
        self.tick = 0
        return True


@dataclass(frozen=True)
class ProtectionDependencies:
    """Represent ProtectionDependencies."""

    logger: Callable[[str], None]
    debugger: Callable[[str], None]
    journal: Callable[[], OrderJournal | None]
    get_order: Callable[[str, int], Dict[str, Any] | None]
    recover_existing_protection: Callable[[str], bool]
    poll_trades: Callable[[str], None]
    pick_oco_prices: Callable[
        [str, List[float], object, object], tuple[object, object, object]
    ]
    average_entry: Callable[[str, int, int], Optional[object]]
    profit_floor_pct: Callable[[], float]
    pull_filters: Callable[[str], Any]
    get_symbol_assets: Callable[[str], tuple[str, str]]
    get_balances: Callable[[], Dict[str, Dict[str, object]]]
    round_price: Callable[[str, object], object]
    round_quantity: Callable[[str, object], object]
    min_quantity: Callable[[str, object], object]
    min_notional: Callable[[str, object], object]
    format_price: Callable[[str, object], str]
    format_quantity: Callable[[str, object], str]
    halt: Callable[..., None]
    place_oco_sell: Callable[..., Dict[str, Any] | None]
    place_limit_order: Callable[..., Dict[str, Any] | None]
    list_open_orders: Callable[[str], List[Dict[str, Any]]]
    tick_size: Callable[[str], object]
    price_eps_mult: Callable[[], float]
    round_step: Callable[[object, object, str], object]
    cancel_oco: Callable[[str, int], None]
    place_market_order: Optional[Callable[..., Dict[str, Any] | None]] = None
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    lot_id_for_fill: Optional[Callable[[str, object, int | None], int | None]] = None


def emergency_gap_flatten(
    symbol: str, current_price: float, *, dependencies: ProtectionDependencies,
    gap_tolerance_pct: float = 0.0,
) -> bool:
    """Handle emergency gap flatten."""
    try:
        current = Decimal(str(current_price))
        tolerance = max(Decimal("0"), Decimal(str(gap_tolerance_pct)))
        orders = dependencies.list_open_orders(symbol) or []
        breached = []
        for order in orders:
            if str(order.get("side", "")).upper() != "SELL":
                continue
            stop = Decimal(str(order.get("stopPrice", 0) or 0))
            if stop > 0 and current < stop * (Decimal("1") - tolerance):
                breached.append(order)
        if not breached:
            return False
        seen_lists = {int(item["orderListId"]) for item in breached if item.get("orderListId") is not None}
        for list_id in seen_lists:
            dependencies.cancel_oco(symbol, list_id)
        dependencies.sleep(0.2)
        base, _ = dependencies.get_symbol_assets(symbol)
        balances = dependencies.get_balances() or {}
        free = Decimal(str((balances.get(base) or {}).get("free", 0) or 0))
        pull_filters = getattr(dependencies, "pull_filters", None)
        filters = exact_symbol_filters(
            pull_filters(symbol) if callable(pull_filters) else None
        )
        if filters is not None:
            qty = round_step(
                max(Decimal("0"), free - filters.minimum_quantity),
                filters.step,
                "floor",
            )
        else:
            minimum = Decimal(str(dependencies.min_quantity(symbol, Decimal("0"))))
            qty = Decimal(str(dependencies.round_quantity(
                symbol, max(Decimal("0"), free - minimum)
            )))
        if qty <= 0:
            dependencies.halt("gap below STOP_LIMIT: no free quantity after OCO cancel", symbol=symbol)
            return False
        result = dependencies.place_market_order(symbol, "SELL", qty) if dependencies.place_market_order else None
        if not result:
            dependencies.halt("gap below STOP_LIMIT: MARKET flatten not confirmed", symbol=symbol)
            return False
        dependencies.logger(f"[GAP-FLATTEN] {symbol} MARKET SELL qty={qty}")
        return True
    except _PROTECTION_DATA_ERRORS as exc:
        dependencies.halt(f"gap watchdog failed: {exc}", symbol=symbol)
        return False


class BreakevenStateStore:
    """Represent BreakevenStateStore."""

    def __init__(
        self,
        run_dir: Callable[[], str],
        debugger: Callable[[str], None],
    ) -> None:
        self._run_dir = run_dir
        self._debugger = debugger

    def _path(self, symbol: str) -> str:
        return os.path.join(self._run_dir(), f"oco_be_state_{symbol}.json")

    def load(self, symbol: str) -> dict:
        try:
            path = self._path(symbol)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle) or {}
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            self._debugger(f"[BE] state load err: {exc}")
        return {}

    def save(self, symbol: str, state: dict) -> None:
        try:
            path = self._path(symbol)
            os.makedirs(os.path.dirname(path) or self._run_dir(), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
        except (OSError, TypeError, ValueError) as exc:
            self._debugger(f"[BE] state save err: {exc}")


def protect_filled_buys(
    symbol: str,
    order_ids: Sequence[int],
    ladder_prices: List[float],
    *,
    config: ProtectionConfig,
    panic_active: bool,
    breakeven_enabled: bool,
    state_store: BreakevenStateStore,
    dependencies: ProtectionDependencies,
    terminal_unfilled_order_ids: Optional[MutableSet[int]] = None,
) -> List[int]:
    """Protect executed BUYs and return order IDs still awaiting a terminal result."""
    remaining = list(order_ids)
    for order_id in list(remaining):
        order = dependencies.get_order(symbol, order_id)
        if not order:
            continue
        status = str(order.get("status", "")).upper()
        try:
            executed_quantity = Decimal(
                str(order.get("executedQty", "0") or "0")
            )
            if not executed_quantity.is_finite() or executed_quantity < 0:
                raise InvalidOperation("invalid executed quantity")
        except (InvalidOperation, TypeError, ValueError) as exc:
            reason = (
                f"invalid executed quantity for BUY order {order_id}: {exc}"
            )
            dependencies.logger(f"[PROTECTION-ERR] {symbol} {reason}")
            dependencies.halt(reason, symbol=symbol, order_id=order_id)
            continue
        # A terminal zero-fill BUY cannot require OCO protection. Supervisory
        # TTL cleanup may cancel it while this worker is polling, so remove it
        # immediately instead of reporting OCO:pending until the worker exits.
        if status in TERMINAL_EXCHANGE_STATES and executed_quantity == 0:
            try:
                journal = dependencies.journal()
                intent = (
                    journal.get_by_exchange_order_id(order_id)
                    if journal is not None
                    else None
                )
                if journal is not None and intent is not None:
                    journal.record_exchange_order(intent.client_order_id, order)
            except (sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
                dependencies.logger(
                    f"[PROTECTION-JOURNAL] {symbol} order={order_id}: {exc}"
                )
            if terminal_unfilled_order_ids is not None:
                terminal_unfilled_order_ids.add(order_id)
            dependencies.logger(
                f"[PROTECTION] {symbol} BUY order={order_id} "
                f"state={status} executed=0; OCO not needed"
            )
            remaining.remove(order_id)
            continue

        terminal_partial = (
            status in TERMINAL_EXCHANGE_STATES and executed_quantity > 0
        )
        if status != "FILLED" and not terminal_partial:
            continue

        protected = False
        journal = dependencies.journal()
        buy_intent = (
            journal.get_by_exchange_order_id(order_id)
            if journal is not None
            else None
        )
        parent_client_id = (
            buy_intent.client_order_id if buy_intent is not None else None
        )
        try:
            # First persist the terminal BUY. If OCO fails midway, the next
            # run will see a position that still requires protection.
            if journal is not None and parent_client_id:
                journal.record_exchange_order(parent_client_id, order)
            if (
                parent_client_id
                and dependencies.recover_existing_protection(parent_client_id)
            ):
                dependencies.logger(
                    f"[RECOVERY] protection already exists for BUY "
                    f"order={order_id}"
                )
                dependencies.poll_trades(symbol)
                remaining.remove(order_id)
                continue
            if executed_quantity <= 0:
                remaining.remove(order_id)
                continue

            cumulative_quote = Decimal(
                str(order.get("cummulativeQuoteQty", "0") or "0")
            )
            average_fill_decimal = cumulative_quote / executed_quantity
            if average_fill_decimal <= 0:
                average_fill_decimal = Decimal(
                    str(order.get("price", "0") or "0")
                )
            if not average_fill_decimal.is_finite() or average_fill_decimal <= 0:
                raise ValueError("BUY fill has no positive average price")
            tp_limit, sl_stop, sl_limit = dependencies.pick_oco_prices(
                symbol,
                ladder_prices,
                average_fill_decimal,
                config.stop_limit_offset_pct,
            )

            # In normal mode TP never falls below average entry and the fee
            # floor. Panic mode allows only the configured discount.
            try:
                average_position = dependencies.average_entry(
                    symbol,
                    config.avg_cache_ttl,
                    config.avg_lookback,
                )
            except (
                ArithmeticError,
                RuntimeError,
                sqlite3.Error,
                TypeError,
                ValueError,
                requests.RequestException,
            ):
                average_position = None
            if average_position is not None:
                average_position_decimal = Decimal(str(average_position))
                minimum_guard: Optional[Decimal] = None
                if panic_active:
                    if config.panic_sell_floor_pct is not None:
                        panic_floor = max(
                            Decimal("0"),
                            Decimal(str(config.panic_sell_floor_pct)),
                        )
                        minimum_guard = average_position_decimal * (
                            Decimal("1") - panic_floor
                        )
                else:
                    minimum_guard = max(
                        average_position_decimal,
                        average_fill_decimal
                        * (
                            Decimal("1")
                            + Decimal(str(dependencies.profit_floor_pct()))
                        ),
                    )
                if (
                    minimum_guard is not None
                    and Decimal(str(tp_limit)) < minimum_guard
                ):
                    exact_filters = exact_symbol_filters(
                        dependencies.pull_filters(symbol)
                    )
                    guard_floor = (
                        round_step(minimum_guard, exact_filters.tick, "ceil")
                        if exact_filters is not None
                        else Decimal(str(dependencies.round_price(
                            symbol, minimum_guard
                        )))
                    )
                    if guard_floor > Decimal(str(tp_limit)):
                        dependencies.debugger(
                            f"[GUARD] {symbol} TP raised: "
                            f"{dependencies.format_price(symbol, tp_limit)} → "
                            f"{dependencies.format_price(symbol, guard_floor)} "
                            f"(avg={dependencies.format_price(symbol, average_position)})"
                        )
                        tp_limit = guard_floor

            exact_filters = exact_symbol_filters(
                dependencies.pull_filters(symbol)
            )
            base, _ = dependencies.get_symbol_assets(symbol)
            balances = dependencies.get_balances()
            base_free = Decimal(
                str(balances.get(base, {}).get("free", 0.0))
            )
            dust = (
                exact_filters.minimum_quantity
                if exact_filters is not None
                else Decimal(str(dependencies.min_quantity(symbol, 0)))
            )
            sellable = max(Decimal("0"), base_free - dust)
            if exact_filters is not None:
                quantity = round_step(
                    min(executed_quantity, sellable),
                    exact_filters.step,
                    "floor",
                )
                tp_rounded = round_step(
                    Decimal(str(tp_limit)), exact_filters.tick, "floor"
                )
                sl_rounded = round_step(
                    Decimal(str(sl_limit)), exact_filters.tick, "floor"
                )
                min_tp = exact_filters.minimum_notional
                min_sl = exact_filters.minimum_notional
            else:
                quantity = Decimal(str(dependencies.round_quantity(
                    symbol, min(executed_quantity, sellable)
                )))
                tp_rounded = Decimal(str(dependencies.round_price(
                    symbol, tp_limit
                )))
                sl_rounded = Decimal(str(dependencies.round_price(
                    symbol, sl_limit
                )))
                min_tp = Decimal(str(dependencies.min_notional(
                    symbol, tp_rounded
                )))
                min_sl = Decimal(str(dependencies.min_notional(
                    symbol, sl_rounded
                )))
            tp_value = quantity * tp_rounded
            sl_value = quantity * sl_rounded
            if quantity <= 0 or tp_value < min_tp or sl_value < min_sl:
                reason = (
                    "cannot protect filled BUY: quantity/notional too small | "
                    "symbol=%s order=%s q=%s sellable=%s dust=%s "
                    "TPv=%.2f<minTP=%.2f SLv=%.2f<minSL=%.2f | "
                    "tp=%s sl_lim=%s"
                    % (
                        symbol,
                        order_id,
                        dependencies.format_quantity(symbol, quantity),
                        dependencies.format_quantity(symbol, sellable),
                        dependencies.format_quantity(symbol, dust),
                        tp_value,
                        min_tp,
                        sl_value,
                        min_sl,
                        dependencies.format_price(symbol, tp_rounded),
                        dependencies.format_price(symbol, sl_rounded),
                    )
                )
                dependencies.halt(
                    reason,
                    symbol=symbol,
                    order_id=order_id,
                    client_order_id=parent_client_id,
                )
                continue

            lot_id = dependencies.lot_id_for_fill(
                symbol, average_fill_decimal, order_id
            ) if dependencies.lot_id_for_fill else None
            oco = dependencies.place_oco_sell(
                symbol,
                quantity,
                tp_rounded,
                sl_stop,
                sl_rounded,
                parent_client_order_id=parent_client_id,
                lot_id=lot_id,
            )
            protected = bool(oco)
            if not oco and config.oco_fallback == "prefer-tp1" and os.getenv("BOT_LIVE_CONFIRMED") == "YES":
                # A single TP in LIVE leaves the position without a stop loss.
                # First flatten the confirmed executed quantity, then persist
                # a halt with the exact reason.
                reason = "OCO was not created: fallback prefer-tp1 is forbidden in LIVE because it leaves the position without a stop"
                try:
                    if dependencies.place_market_order is not None:
                        dependencies.place_market_order(
                            symbol, "SELL", quantity
                        )
                except (OSError, RuntimeError, ValueError, TypeError) as exc:
                    dependencies.logger(f"[FLATTEN-ERR] {symbol}: {exc}")
                dependencies.halt(reason, symbol=symbol, order_id=order_id,
                                  client_order_id=parent_client_id)
                continue
            if not oco and config.oco_fallback == "prefer-tp1":
                try:
                    fallback = dependencies.place_limit_order(
                        "SELL",
                        symbol,
                        quantity,
                        tp_rounded,
                        maker=config.sell_limit_maker,
                        purpose="fallback_tp",
                        parent_client_order_id=parent_client_id,
                    )
                    if fallback:
                        protected = True
                        if journal is not None and parent_client_id:
                            fallback_client_id = str(
                                fallback.get("clientOrderId") or ""
                            )
                            if fallback_client_id:
                                journal.mark_protected(
                                    parent_client_order_id=parent_client_id,
                                    protection_client_order_id=fallback_client_id,
                                    exchange_order_id=(
                                        int(fallback["orderId"])
                                        if fallback.get("orderId") is not None
                                        else None
                                    ),
                                )
                        dependencies.logger(
                            f"[FALLBACK] {symbol} single TP placed @ "
                            f"{dependencies.format_price(symbol, tp_rounded)}"
                        )
                except (
                    OSError,
                    RuntimeError,
                    sqlite3.Error,
                    TypeError,
                    ValueError,
                    requests.RequestException,
                ) as exc:
                    dependencies.logger(
                        f"[FALLBACK-ERR] {symbol} -> {type(exc).__name__}"
                    )

            if oco and breakeven_enabled:
                try:
                    order_list_id = int(oco.get("orderListId") or 0)
                    if order_list_id:
                        state = state_store.load(symbol)
                        state[str(order_list_id)] = {
                            "fill_price": format(average_fill_decimal, "f"),
                            "tp_price": format(tp_rounded, "f"),
                            "ts": dependencies.now(),
                        }
                        state_store.save(symbol, state)
                        dependencies.debugger(
                            f"[BE] state add: orderListId={order_list_id} "
                            f"fill={dependencies.format_price(symbol, average_fill_decimal)}"
                        )
                except (TypeError, ValueError) as exc:
                    dependencies.debugger(f"[BE] state add err: {exc}")

            if not protected:
                dependencies.halt(
                    f"filled BUY {order_id} has no confirmed OCO or "
                    "fallback protection",
                    symbol=symbol,
                    order_id=order_id,
                    client_order_id=parent_client_id,
                )
        except Exception as exc:
            # This is the final protection boundary. It deliberately catches
            # unexpected implementation failures so a filled LIVE BUY can
            # never continue unprotected. Only the exception type is emitted;
            # transport exceptions can contain signed query strings.
            error_type = type(exc).__name__
            dependencies.logger(
                f"[ATTACH-OCO-ERR] {symbol} order {order_id}: {error_type}"
            )
            dependencies.halt(
                f"protection error for filled BUY {order_id}: {error_type}",
                symbol=symbol,
                order_id=order_id,
                client_order_id=parent_client_id,
            )

        if protected:
            # Update the ledger only after protection is confirmed; otherwise
            # the supervisor may see a falsely safe position.
            dependencies.poll_trades(symbol)
            try:
                remaining.remove(order_id)
            except ValueError:
                pass
    return remaining


def maintain_breakeven(
    symbol: str,
    *,
    offset_pct: float,
    stop_limit_offset_pct: float,
    state_store: BreakevenStateStore,
    dependencies: ProtectionDependencies,
) -> None:
    """Maintain breakeven."""
    try:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for order in dependencies.list_open_orders(symbol):
            try:
                if str(order.get("side", "")).upper() != "SELL":
                    continue
                order_list_id = order.get("orderListId")
                if not order_list_id:
                    continue
                groups.setdefault(str(order_list_id), []).append(order)
            except (AttributeError, TypeError, ValueError):
                continue
        if not groups:
            return
        state = state_store.load(symbol)
        for order_list_id, orders in groups.items():
            take_profit = next(
                (
                    item
                    for item in orders
                    if "LIMIT" in str(item.get("type", "")).upper()
                    and "STOP" not in str(item.get("type", "")).upper()
                ),
                None,
            )
            stop_loss = next(
                (
                    item
                    for item in orders
                    if "STOP_LOSS" in str(item.get("type", "")).upper()
                ),
                None,
            )
            if not take_profit or not stop_loss:
                continue
            try:
                original = Decimal(str(
                    take_profit.get("origQty", "0") or "0"
                ))
                executed = Decimal(str(
                    take_profit.get("executedQty", "0") or "0"
                ))
                remaining = max(Decimal("0"), original - executed)
            except (InvalidOperation, TypeError, ValueError):
                continue
            if executed <= 0 or remaining <= 0:
                continue

            fill_price = Decimal(str(
                state.get(str(order_list_id), {}).get("fill_price", "0")
            ))
            if fill_price <= 0:
                continue
            exact_filters = exact_symbol_filters(
                dependencies.pull_filters(symbol)
            )
            offset = max(Decimal("0"), Decimal(str(offset_pct)))
            target_raw = fill_price * (Decimal("1") + offset)
            target_stop = (
                round_step(target_raw, exact_filters.tick, "floor")
                if exact_filters is not None
                else Decimal(str(dependencies.round_price(
                    symbol, target_raw
                )))
            )
            try:
                current_stop = Decimal(str(
                    stop_loss.get("stopPrice", "0") or "0"
                ))
            except (InvalidOperation, TypeError, ValueError):
                current_stop = Decimal("0")
            if current_stop >= target_stop:
                continue

            tick = (
                exact_filters.tick
                if exact_filters is not None
                else Decimal(str(dependencies.tick_size(symbol)))
            )
            epsilon = max(
                tick * max(
                    Decimal("1"),
                    Decimal(str(dependencies.price_eps_mult())),
                ),
                fill_price * max(
                    Decimal("0"), Decimal(str(stop_limit_offset_pct))
                ),
            )
            sl_stop = round_step(target_stop, tick, "up")
            sl_limit = round_step(sl_stop - epsilon, tick, "down")
            if sl_stop <= sl_limit:
                sl_stop = round_step(sl_limit + tick, tick, "up")
            try:
                tp_price = Decimal(str(
                    take_profit.get("price", "0") or "0"
                ))
            except (InvalidOperation, TypeError, ValueError):
                tp_price = Decimal("0")
            if tp_price <= 0:
                continue

            if exact_filters is not None:
                remaining = round_step(
                    remaining, exact_filters.step, "floor"
                )
                minimum_quantity = exact_filters.minimum_quantity
                min_tp = exact_filters.minimum_notional
                min_sl = exact_filters.minimum_notional
            else:
                remaining = Decimal(str(dependencies.round_quantity(
                    symbol, remaining
                )))
                minimum_quantity = Decimal(str(
                    dependencies.min_quantity(symbol, 0)
                ))
                min_tp = Decimal(str(dependencies.min_notional(
                    symbol, tp_price
                )))
                min_sl = Decimal(str(dependencies.min_notional(
                    symbol, sl_limit
                )))
            if remaining < minimum_quantity:
                dependencies.debugger(
                    f"[BE] skip dust remain="
                    f"{dependencies.format_quantity(symbol, remaining)}"
                )
                continue
            if remaining * tp_price < min_tp:
                dependencies.debugger(
                    f"[BE] skip TP notional too small: "
                    f"{remaining * tp_price:.2f} < {min_tp:.2f}"
                )
                continue
            if remaining * sl_limit < min_sl:
                dependencies.debugger(
                    f"[BE] skip SL notional too small: "
                    f"{remaining * sl_limit:.2f} < {min_sl:.2f}"
                )
                continue

            try:
                dependencies.cancel_oco(symbol, int(order_list_id))
                dependencies.sleep(0.25)
            except _PROTECTION_DATA_ERRORS as exc:
                # A lost cancel response is not permission to create another
                # OCO. Query Binance and proceed only when the old list is
                # conclusively absent.
                try:
                    refreshed_orders = dependencies.list_open_orders(symbol) or []
                except _PROTECTION_DATA_ERRORS as verify_exc:
                    dependencies.halt(
                        "breakeven OCO cancel reconciliation unavailable",
                        symbol=symbol,
                        order_list_id=int(order_list_id),
                        cancel_error_type=exc.__class__.__name__,
                        verify_error_type=verify_exc.__class__.__name__,
                    )
                    dependencies.logger(
                        f"[BE-CANCEL-UNKNOWN] {symbol} orderListId={order_list_id} "
                        f"cancel_error={exc.__class__.__name__} "
                        f"verify_error={verify_exc.__class__.__name__}"
                    )
                    continue
                old_list_open = any(
                    str(order.get("orderListId", "")) == str(order_list_id)
                    for order in refreshed_orders
                    if isinstance(order, dict)
                )
                if old_list_open:
                    dependencies.halt(
                        "breakeven OCO cancel not confirmed; old list remains open",
                        symbol=symbol,
                        order_list_id=int(order_list_id),
                        cancel_error_type=exc.__class__.__name__,
                    )
                    dependencies.logger(
                        f"[BE-CANCEL-OPEN] {symbol} orderListId={order_list_id}"
                    )
                    continue
                dependencies.logger(
                    f"[BE-CANCEL-RECOVERED] {symbol} orderListId={order_list_id} "
                    "confirmed absent"
                )
            replacement = dependencies.place_oco_sell(
                symbol,
                remaining,
                tp_price,
                sl_stop,
                sl_limit,
            )
            if not replacement:
                continue
            try:
                new_order_list_id = int(
                    replacement.get("orderListId") or 0
                )
            except (AttributeError, TypeError, ValueError):
                new_order_list_id = 0
            if new_order_list_id:
                state.pop(str(order_list_id), None)
                state[str(new_order_list_id)] = {
                    "fill_price": format(fill_price, "f"),
                    "tp_price": format(tp_price, "f"),
                    "ts": dependencies.now(),
                }
                state_store.save(symbol, state)
                dependencies.logger(
                    f"[BE] {symbol} OCO re-arm -> BE stop="
                    f"{dependencies.format_price(symbol, sl_stop)} "
                    f"(orderListId={new_order_list_id})"
                )
    except _PROTECTION_DATA_ERRORS as exc:
        dependencies.debugger(
            f"[BE] loop err type={type(exc).__name__}"
        )
