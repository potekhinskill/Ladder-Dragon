# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor protection component of the execution layer.
"""Ladder Dragon position-protection runtime."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, MutableSet, Optional, Sequence

import requests

from ladder_dragon.execution.order_recovery import OrderJournal, TERMINAL_EXCHANGE_STATES
from ladder_dragon.execution.exchange_math import exact_symbol_filters, round_step
from ladder_dragon.execution.protection.validation import (
    exact_balance_quantity as _exact_balance_quantity,
)


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
    market_price: Optional[Callable[[str], object]] = None
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    lot_id_for_fill: Optional[Callable[[str, object, int | None], int | None]] = None
    average_entry_for_position: Optional[Callable[[str, object, int, int], Optional[object]]] = None


def _remaining_oco_quantity(order: Dict[str, Any]) -> Decimal:
    original = Decimal(str(order.get("origQty", 0) or 0))
    executed = Decimal(str(order.get("executedQty", 0) or 0))
    if (
        not original.is_finite()
        or not executed.is_finite()
        or original <= 0
        or executed < 0
        or executed > original
    ):
        raise ValueError("breached OCO has invalid quantity state")
    return original - executed


def _confirmed_market_fill(
    result: Dict[str, Any] | None,
    expected_quantity: Decimal,
) -> tuple[bool, Decimal, str]:
    if not isinstance(result, dict):
        return False, Decimal("0"), "MISSING"
    status = str(result.get("status") or "UNKNOWN").upper()
    try:
        executed = Decimal(str(result.get("executedQty", 0) or 0))
    except (InvalidOperation, TypeError, ValueError):
        return False, Decimal("0"), status
    if not executed.is_finite() or executed < 0:
        return False, Decimal("0"), status
    return (
        status == "FILLED" and executed >= expected_quantity,
        executed,
        status,
    )


def _emergency_flatten_unprotected_fill(
    symbol: str,
    order_id: int,
    quantity: Decimal,
    *,
    parent_client_id: str | None,
    reason: str,
    dependencies: ProtectionDependencies,
) -> bool:
    """Flatten a filled BUY and durably close its parent only after exact ACK."""
    result = None
    error_type = None
    try:
        if dependencies.place_market_order is not None:
            result = dependencies.place_market_order(
                symbol,
                "SELL",
                quantity,
                parent_client_order_id=parent_client_id,
            )
    except _PROTECTION_DATA_ERRORS as exc:
        error_type = type(exc).__name__
        dependencies.logger(
            f"[PROTECTION-FLATTEN-ERR] {symbol} order={order_id}: "
            f"{error_type}"
        )

    confirmed, executed, status = _confirmed_market_fill(result, quantity)
    if not confirmed:
        halt_reason = (
            f"{reason}; emergency MARKET flatten not fully confirmed "
            f"expected={quantity} executed={executed} status={status}"
        )
        if error_type:
            halt_reason += f" error={error_type}"
        dependencies.halt(
            halt_reason,
            symbol=symbol,
            order_id=order_id,
            client_order_id=parent_client_id,
        )
        return False

    journal = dependencies.journal()
    if journal is not None and parent_client_id:
        try:
            journal.update_metadata(
                parent_client_id,
                {
                    "emergency_exit": True,
                    "emergency_exit_reason": reason,
                    "exit_order_id": int(result["orderId"]),
                    "closed_at": dependencies.now(),
                },
            )
            journal.mark_closed(parent_client_id)
        except (KeyError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            dependencies.halt(
                f"{reason}; MARKET flatten confirmed but journal closure failed "
                f"error={type(exc).__name__}",
                symbol=symbol,
                order_id=order_id,
                client_order_id=parent_client_id,
            )
            return False

    dependencies.poll_trades(symbol)
    dependencies.logger(
        f"[PROTECTION-FLATTEN] {symbol} order={order_id} "
        f"expected={quantity} executed={executed} reason={reason}"
    )
    dependencies.halt(
        f"{reason}; emergency MARKET flatten confirmed "
        f"expected={quantity} executed={executed}",
        symbol=symbol,
        order_id=order_id,
        client_order_id=parent_client_id,
    )
    return True


def emergency_gap_flatten(
    symbol: str, current_price: float, *, dependencies: ProtectionDependencies,
    gap_tolerance_pct: float = 0.0,
    cancel_release_timeout_sec: float = 5.0,
    cancel_release_poll_sec: float = 0.1,
) -> bool:
    """Cancel breached OCO lists and confirm the complete residual flatten."""
    try:
        current = Decimal(str(current_price))
        tolerance = max(Decimal("0"), Decimal(str(gap_tolerance_pct)))
        orders = dependencies.list_open_orders(symbol) or []
        breached: list[Dict[str, Any]] = []
        for order in orders:
            if str(order.get("side", "")).upper() != "SELL":
                continue
            stop = Decimal(str(order.get("stopPrice", 0) or 0))
            if stop > 0 and current < stop * (Decimal("1") - tolerance):
                breached.append(order)
        if not breached:
            return False

        seen_lists: set[int] = set()
        for item in breached:
            if item.get("orderListId") is None:
                raise ValueError("breached protection has no OCO list id")
            seen_lists.add(int(item["orderListId"]))

        # Use both legs when available. A partially filled TP can reduce the
        # protected residual while the STOP leg still reports its original
        # quantity; the smaller remaining leg is the authoritative exposure.
        quantities_by_list: dict[int, list[Decimal]] = {}
        for item in orders:
            if (
                str(item.get("side", "")).upper() != "SELL"
                or item.get("orderListId") is None
            ):
                continue
            list_id = int(item["orderListId"])
            if list_id not in seen_lists:
                continue
            quantities_by_list.setdefault(list_id, []).append(
                _remaining_oco_quantity(item)
            )
        if set(quantities_by_list) != seen_lists:
            raise ValueError("breached OCO quantity state is incomplete")
        expected_quantity = sum(
            (
                min(quantities)
                for quantities in quantities_by_list.values()
                if quantities
            ),
            Decimal("0"),
        )
        if expected_quantity <= 0:
            raise ValueError("breached OCO has no positive residual quantity")

        base, _ = dependencies.get_symbol_assets(symbol)
        initial_balances = dependencies.get_balances() or {}
        initial_free = _exact_balance_quantity(initial_balances, base, "free")
        initial_locked = _exact_balance_quantity(
            initial_balances, base, "locked"
        )
        initial_total = initial_free + initial_locked
        if initial_total < expected_quantity:
            raise ValueError(
                "account base balance is below breached OCO residual"
            )

        for list_id in seen_lists:
            dependencies.cancel_oco(symbol, list_id)

        pull_filters = getattr(dependencies, "pull_filters", None)
        filters = exact_symbol_filters(
            pull_filters(symbol) if callable(pull_filters) else None
        )

        raw_timeout = Decimal(str(cancel_release_timeout_sec))
        raw_poll_interval = Decimal(str(cancel_release_poll_sec))
        if (
            not raw_timeout.is_finite()
            or not raw_poll_interval.is_finite()
        ):
            raise ValueError("gap cancel-release timing must be finite")
        timeout = max(Decimal("0.1"), raw_timeout)
        poll_interval = max(Decimal("0.01"), raw_poll_interval)
        sleep_seconds = (
            cancel_release_poll_sec
            if raw_poll_interval >= Decimal("0.01")
            else 0.01
        )
        maximum_attempts = max(
            1,
            int(
                (timeout / poll_interval).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
            + 1,
        )
        started_at = dependencies.now()
        quantity = Decimal("0")
        free = initial_free
        locked = initial_locked
        remaining_expected = expected_quantity
        for attempt in range(maximum_attempts):
            current_orders = dependencies.list_open_orders(symbol) or []
            still_open = {
                int(item["orderListId"])
                for item in current_orders
                if item.get("orderListId") is not None
                and int(item["orderListId"]) in seen_lists
            }
            balances = dependencies.get_balances() or {}
            free = _exact_balance_quantity(balances, base, "free")
            locked = _exact_balance_quantity(balances, base, "locked")
            sold_during_cancel = max(
                Decimal("0"),
                initial_total - (free + locked),
            )
            remaining_expected = max(
                Decimal("0"),
                expected_quantity - sold_during_cancel,
            )
            if filters is not None:
                quantity = round_step(
                    remaining_expected,
                    filters.step,
                    "floor",
                )
                minimum_quantity = filters.minimum_quantity
            else:
                quantity = Decimal(str(dependencies.round_quantity(
                    symbol,
                    remaining_expected,
                )))
                minimum_quantity = Decimal(str(
                    dependencies.min_quantity(symbol, Decimal("0"))
                ))

            if not still_open:
                if remaining_expected == 0:
                    dependencies.logger(
                        f"[GAP-FLATTEN] {symbol} breached OCO filled during "
                        f"cancel qty={expected_quantity}"
                    )
                    return True
                if quantity <= 0 or quantity < minimum_quantity:
                    dependencies.halt(
                        "gap below STOP_LIMIT: residual quantity is below "
                        "exchange minimum after OCO cancel",
                        symbol=symbol,
                    )
                    return False
                if free >= quantity:
                    break

            elapsed = Decimal(str(dependencies.now() - started_at))
            if attempt + 1 >= maximum_attempts or elapsed >= timeout:
                dependencies.halt(
                    "gap below STOP_LIMIT: OCO cancel/free-balance release "
                    f"not confirmed expected={expected_quantity} "
                    f"free={free} locked={locked}",
                    symbol=symbol,
                )
                return False
            dependencies.sleep(sleep_seconds)

        result = (
            dependencies.place_market_order(symbol, "SELL", quantity)
            if dependencies.place_market_order else None
        )
        confirmed, executed, status = _confirmed_market_fill(
            result,
            quantity,
        )
        if not confirmed:
            dependencies.halt(
                "gap below STOP_LIMIT: MARKET flatten incomplete "
                f"expected={quantity} executed={executed} status={status}",
                symbol=symbol,
            )
            return False
        dependencies.logger(
            f"[GAP-FLATTEN] {symbol} MARKET SELL "
            f"expected={quantity} executed={executed}"
        )
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
            exited_quantity = Decimal("0")
            if journal is not None and parent_client_id:
                partial_exit_reader = getattr(
                    journal,
                    "partial_protection_exit_quantity",
                    None,
                )
                if callable(partial_exit_reader):
                    exited_quantity = partial_exit_reader(parent_client_id)
                if exited_quantity > executed_quantity:
                    raise RuntimeError(
                        "confirmed partial protection exits exceed BUY fill"
                    )
            quantity_requiring_protection = executed_quantity - exited_quantity
            if quantity_requiring_protection <= 0:
                dependencies.poll_trades(symbol)
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

            # Reuse one authoritative account snapshot throughout protection.
            exact_filters = exact_symbol_filters(dependencies.pull_filters(symbol))
            base, _ = dependencies.get_symbol_assets(symbol)
            balances = dependencies.get_balances()
            base_free = _exact_balance_quantity(balances, base, "free")
            position_quantity = base_free + _exact_balance_quantity(
                balances, base, "locked"
            )

            # In normal mode TP never falls below average entry and the fee
            # floor. Panic mode allows only the configured discount.
            try:
                if dependencies.average_entry_for_position is not None:
                    average_position = dependencies.average_entry_for_position(
                        symbol, position_quantity, config.avg_cache_ttl,
                        config.avg_lookback
                    )
                else:
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

            sellable = max(Decimal("0"), base_free)
            if exact_filters is not None:
                quantity = round_step(
                    min(quantity_requiring_protection, sellable),
                    exact_filters.step,
                    "floor",
                )
                tp_rounded = round_step(
                    Decimal(str(tp_limit)), exact_filters.tick, "ceil"
                )
                stop_rounded = round_step(
                    Decimal(str(sl_stop)), exact_filters.tick, "ceil"
                )
                sl_rounded = round_step(
                    Decimal(str(sl_limit)), exact_filters.tick, "floor"
                )
                min_tp = exact_filters.minimum_notional
                min_sl = exact_filters.minimum_notional
            else:
                quantity = Decimal(str(dependencies.round_quantity(
                    symbol, min(quantity_requiring_protection, sellable)
                )))
                tp_rounded = Decimal(str(dependencies.round_price(
                    symbol, tp_limit
                )))
                stop_rounded = Decimal(str(dependencies.round_price(
                    symbol, sl_stop
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
                    "symbol=%s order=%s q=%s sellable=%s "
                    "TPv=%.2f<minTP=%.2f SLv=%.2f<minSL=%.2f | "
                    "tp=%s sl_lim=%s"
                    % (
                        symbol,
                        order_id,
                        dependencies.format_quantity(symbol, quantity),
                        dependencies.format_quantity(symbol, sellable),
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

            # Binance requires SELL OCO prices to satisfy
            # TP > current market > STOP > STOP_LIMIT. A STOP already crossed
            # while the BUY fill was being reconciled cannot protect the lot;
            # submitting it only produces -2010 and leaves inventory exposed.
            if dependencies.market_price is not None:
                fresh_market = Decimal(
                    str(dependencies.market_price(symbol))
                )
                if (
                    not fresh_market.is_finite()
                    or fresh_market <= 0
                ):
                    raise ValueError("fresh market price is invalid")
                if not (
                    tp_rounded > fresh_market > stop_rounded > sl_rounded
                ):
                    reason = (
                        "fresh market crossed planned OCO relationship "
                        f"tp={tp_rounded} market={fresh_market} "
                        f"stop={stop_rounded} limit={sl_rounded}"
                    )
                    flattened = _emergency_flatten_unprotected_fill(
                        symbol,
                        order_id,
                        quantity,
                        parent_client_id=parent_client_id,
                        reason=reason,
                        dependencies=dependencies,
                    )
                    if flattened:
                        remaining.remove(order_id)
                    continue

            lot_id = dependencies.lot_id_for_fill(
                symbol, average_fill_decimal, order_id
            ) if dependencies.lot_id_for_fill else None
            oco = dependencies.place_oco_sell(
                symbol,
                quantity,
                tp_rounded,
                stop_rounded,
                sl_rounded,
                parent_client_order_id=parent_client_id,
                lot_id=lot_id,
            )
            protected = bool(oco)
            if not oco and os.getenv("BOT_LIVE_CONFIRMED") == "YES":
                # Any LIVE OCO rejection is an unprotected filled position,
                # regardless of the configured non-LIVE single-TP fallback.
                flattened = _emergency_flatten_unprotected_fill(
                    symbol,
                    order_id,
                    quantity,
                    parent_client_id=parent_client_id,
                    reason="OCO was not created for filled BUY",
                    dependencies=dependencies,
                )
                if flattened:
                    remaining.remove(order_id)
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
