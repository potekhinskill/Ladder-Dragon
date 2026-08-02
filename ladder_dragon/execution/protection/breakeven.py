# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: maintain breakeven protection after partial take-profit fills.
"""Breakeven protection runtime."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
import time
from typing import Any, Callable, Dict, List, Protocol

import requests

from ladder_dragon.execution.exchange_math import exact_symbol_filters, round_step


_BREAKEVEN_ERRORS = (
    ArithmeticError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    requests.RequestException,
)
_CANCEL_VERIFY_ATTEMPTS = 3
_CANCEL_VERIFY_DELAY_SEC = 0.25


class BreakevenDependencies(Protocol):
    """Define the dependencies required by breakeven maintenance."""

    logger: Callable[[str], None]
    debugger: Callable[[str], None]
    pull_filters: Callable[[str], Any]
    round_price: Callable[[str, object], object]
    round_quantity: Callable[[str, object], object]
    min_quantity: Callable[[str, object], object]
    min_notional: Callable[[str, object], object]
    format_price: Callable[[str, object], str]
    format_quantity: Callable[[str, object], str]
    halt: Callable[..., None]
    place_oco_sell: Callable[..., Dict[str, Any] | None]
    list_open_orders: Callable[[str], List[Dict[str, Any]]]
    tick_size: Callable[[str], object]
    price_eps_mult: Callable[[], float]
    cancel_oco: Callable[[str, int], None]
    sleep: Callable[[float], None]
    now: Callable[[], float]


@dataclass
class BreakevenRuntime:
    """Track the breakeven maintenance interval."""

    enabled: bool
    offset_pct: float
    check_interval: int
    tick: int = 0

    def due(self) -> bool:
        """Return true when maintenance must run."""
        if not self.enabled:
            return False
        self.tick += 1
        if self.tick < max(1, int(self.check_interval)):
            return False
        self.tick = 0
        return True


class BreakevenStateStore:
    """Store the fill price for each protected order list."""

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
        """Load the state for one symbol."""
        try:
            path = self._path(symbol)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle) or {}
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            self._debugger(f"[BE] state load err: {exc}")
        return {}

    def save(self, symbol: str, state: dict) -> None:
        """Save the state for one symbol."""
        try:
            path = self._path(symbol)
            os.makedirs(os.path.dirname(path) or self._run_dir(), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
        except (OSError, TypeError, ValueError) as exc:
            self._debugger(f"[BE] state save err: {exc}")


def _old_order_list_is_absent(
    symbol: str,
    order_list_id: int,
    *,
    cancel_error_type: str | None,
    dependencies: BreakevenDependencies,
) -> bool:
    """Return true only after Binance no longer reports the old OCO."""
    # A cancel ACK proves request acceptance, not the final exchange state.
    # Keep the replacement blocked until Binance stops reporting the old list.
    for attempt in range(_CANCEL_VERIFY_ATTEMPTS):
        try:
            open_orders = dependencies.list_open_orders(symbol) or []
        except _BREAKEVEN_ERRORS as exc:
            dependencies.halt(
                "breakeven OCO cancel reconciliation unavailable",
                symbol=symbol,
                order_list_id=order_list_id,
                cancel_error_type=cancel_error_type,
                verify_error_type=type(exc).__name__,
            )
            dependencies.logger(
                f"[BE-CANCEL-UNKNOWN] {symbol} orderListId={order_list_id} "
                f"cancel_error={cancel_error_type or 'none'} "
                f"verify_error={type(exc).__name__}"
            )
            return False
        old_list_open = any(
            str(order.get("orderListId", "")) == str(order_list_id)
            for order in open_orders
            if isinstance(order, dict)
        )
        if not old_list_open:
            event = "BE-CANCEL-RECOVERED" if cancel_error_type else "BE-CANCEL-CONFIRMED"
            dependencies.logger(
                f"[{event}] {symbol} orderListId={order_list_id} confirmed absent"
            )
            return True
        if attempt + 1 < _CANCEL_VERIFY_ATTEMPTS:
            dependencies.sleep(_CANCEL_VERIFY_DELAY_SEC)

    metadata: Dict[str, Any] = {
        "symbol": symbol,
        "order_list_id": order_list_id,
    }
    if cancel_error_type:
        metadata["cancel_error_type"] = cancel_error_type
    dependencies.halt(
        "breakeven OCO cancel not confirmed; old list remains open",
        **metadata,
    )
    dependencies.logger(
        f"[BE-CANCEL-OPEN] {symbol} orderListId={order_list_id}"
    )
    return False


def _halt_unprotected_rearm(
    symbol: str,
    order_list_id: int,
    *,
    dependencies: BreakevenDependencies,
    error_type: str,
) -> None:
    """Persist a safe diagnostic after the old OCO was removed."""
    # At this boundary, the managed quantity has no confirmed exchange protection.
    # Persist HALT before returning so restarts cannot hide the unsafe state.
    dependencies.halt(
        "breakeven re-arm left position without confirmed protection",
        symbol=symbol,
        order_list_id=order_list_id,
        error_type=error_type,
    )
    dependencies.logger(
        f"[BE-REARM-UNPROTECTED] {symbol} orderListId={order_list_id} "
        f"error={error_type}"
    )


def maintain_breakeven(
    symbol: str,
    *,
    offset_pct: float,
    stop_limit_offset_pct: float,
    state_store: BreakevenStateStore,
    dependencies: BreakevenDependencies,
) -> None:
    """Move a partially filled OCO stop to breakeven."""
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
        for order_list_id_text, orders in groups.items():
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
                original = Decimal(str(take_profit.get("origQty", "0") or "0"))
                executed = Decimal(str(take_profit.get("executedQty", "0") or "0"))
                remaining = max(Decimal("0"), original - executed)
            except (InvalidOperation, TypeError, ValueError):
                continue
            if executed <= 0 or remaining <= 0:
                continue

            fill_price = Decimal(
                str(state.get(order_list_id_text, {}).get("fill_price", "0"))
            )
            if fill_price <= 0:
                continue
            exact_filters = exact_symbol_filters(dependencies.pull_filters(symbol))
            offset = max(Decimal("0"), Decimal(str(offset_pct)))
            target_raw = fill_price * (Decimal("1") + offset)
            target_stop = (
                round_step(target_raw, exact_filters.tick, "floor")
                if exact_filters is not None
                else Decimal(str(dependencies.round_price(symbol, target_raw)))
            )
            try:
                current_stop = Decimal(str(stop_loss.get("stopPrice", "0") or "0"))
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
                tick
                * max(Decimal("1"), Decimal(str(dependencies.price_eps_mult()))),
                fill_price
                * max(Decimal("0"), Decimal(str(stop_limit_offset_pct))),
            )
            sl_stop = round_step(target_stop, tick, "up")
            sl_limit = round_step(sl_stop - epsilon, tick, "down")
            if sl_stop <= sl_limit:
                sl_stop = round_step(sl_limit + tick, tick, "up")
            try:
                tp_price = Decimal(str(take_profit.get("price", "0") or "0"))
            except (InvalidOperation, TypeError, ValueError):
                tp_price = Decimal("0")
            if tp_price <= 0:
                continue

            if exact_filters is not None:
                remaining = round_step(remaining, exact_filters.step, "floor")
                minimum_quantity = exact_filters.minimum_quantity
                min_tp = exact_filters.minimum_notional
                min_sl = exact_filters.minimum_notional
            else:
                remaining = Decimal(str(dependencies.round_quantity(symbol, remaining)))
                minimum_quantity = Decimal(str(dependencies.min_quantity(symbol, 0)))
                min_tp = Decimal(str(dependencies.min_notional(symbol, tp_price)))
                min_sl = Decimal(str(dependencies.min_notional(symbol, sl_limit)))
            if remaining < minimum_quantity:
                dependencies.debugger(
                    f"[BE] skip dust remain={dependencies.format_quantity(symbol, remaining)}"
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

            order_list_id = int(order_list_id_text)
            cancel_error_type: str | None = None
            # Breakeven replacement is destructive: the old OCO is removed first.
            # Reconcile every cancel outcome, including an apparently successful ACK.
            try:
                dependencies.cancel_oco(symbol, order_list_id)
            except _BREAKEVEN_ERRORS as exc:
                cancel_error_type = type(exc).__name__
            if not _old_order_list_is_absent(
                symbol,
                order_list_id,
                cancel_error_type=cancel_error_type,
                dependencies=dependencies,
            ):
                return

            try:
                # place_oco_sell returns only after it verifies both new OCO legs.
                replacement = dependencies.place_oco_sell(
                    symbol,
                    remaining,
                    tp_price,
                    sl_stop,
                    sl_limit,
                )
            except _BREAKEVEN_ERRORS as exc:
                _halt_unprotected_rearm(
                    symbol,
                    order_list_id,
                    dependencies=dependencies,
                    error_type=type(exc).__name__,
                )
                return
            try:
                new_order_list_id = int(replacement.get("orderListId") or 0)
            except (AttributeError, TypeError, ValueError):
                new_order_list_id = 0
            if new_order_list_id <= 0:
                _halt_unprotected_rearm(
                    symbol,
                    order_list_id,
                    dependencies=dependencies,
                    error_type="UnconfirmedReplacement",
                )
                return

            # Change durable ownership only after the replacement list is verified.
            state.pop(order_list_id_text, None)
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
    except _BREAKEVEN_ERRORS as exc:
        dependencies.debugger(f"[BE] loop err type={type(exc).__name__}")


__all__ = [
    "BreakevenDependencies",
    "BreakevenRuntime",
    "BreakevenStateStore",
    "maintain_breakeven",
]
