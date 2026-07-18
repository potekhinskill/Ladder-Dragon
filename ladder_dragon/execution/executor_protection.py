# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: keep the file role and safety boundaries clear during maintenance.
"""Сопровождение исполненных BUY, защитных OCO и breakeven.

Модуль владеет жизненным циклом защиты позиции после исполнения покупки.
Он не подписывает HTTP-запросы самостоятельно: все биржевые операции и доступ
к журналу передаются через зависимости, поэтому сценарии можно тестировать
без ключей и сети.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from ladder_dragon.execution.order_recovery import OrderJournal, TERMINAL_EXCHANGE_STATES


@dataclass(frozen=True)
class ProtectionConfig:
    """Настройки защиты BUY и допустимого резервного SELL."""

    stop_limit_offset_pct: float
    oco_fallback: str
    sell_limit_maker: bool
    avg_cache_ttl: int
    avg_lookback: int
    panic_sell_floor_pct: Optional[float]


@dataclass
class BreakevenRuntime:
    """Счётчик периодической проверки OCO после частичного TP."""

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
    """Поздно связываемые функции исполнителя, необходимые сопровождению."""

    logger: Callable[[str], None]
    debugger: Callable[[str], None]
    journal: Callable[[], OrderJournal | None]
    get_order: Callable[[str, int], Dict[str, Any] | None]
    recover_existing_protection: Callable[[str], bool]
    poll_trades: Callable[[str], None]
    pick_oco_prices: Callable[
        [str, List[float], float, float], tuple[float, float, float]
    ]
    average_entry: Callable[[str, int, int], Optional[float]]
    profit_floor_pct: Callable[[], float]
    pull_filters: Callable[[str], Any]
    get_symbol_assets: Callable[[str], tuple[str, str]]
    get_balances: Callable[[], Dict[str, Dict[str, float]]]
    round_price: Callable[[str, float], float]
    round_quantity: Callable[[str, float], float]
    min_quantity: Callable[[str, float], float]
    min_notional: Callable[[str, float], float]
    format_price: Callable[[str, float], str]
    format_quantity: Callable[[str, float], str]
    halt: Callable[..., None]
    place_oco_sell: Callable[..., Dict[str, Any] | None]
    place_limit_order: Callable[..., Dict[str, Any] | None]
    list_open_orders: Callable[[str], List[Dict[str, Any]]]
    tick_size: Callable[[str], float]
    price_eps_mult: Callable[[], float]
    round_step: Callable[[float, float, str], float]
    cancel_oco: Callable[[str, int], None]
    place_market_order: Optional[Callable[..., Dict[str, Any] | None]] = None
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    lot_id_for_fill: Optional[Callable[[str, float, int | None], int | None]] = None


def emergency_gap_flatten(
    symbol: str, current_price: float, *, dependencies: ProtectionDependencies,
    gap_tolerance_pct: float = 0.0,
) -> bool:
    """Закрыть свободный остаток, если STOP_LIMIT оказался ниже gap-цены.

    Функция не трогает активный stop выше рынка. Она срабатывает только когда
    найден SELL stop, рынок уже ниже stop с заданным допуском, а ордер всё ещё
    открыт. После отмены OCO баланс перечитывается, чтобы не продублировать
    уже исполненный stop.
    """
    try:
        orders = dependencies.list_open_orders(symbol) or []
        breached = []
        for order in orders:
            if str(order.get("side", "")).upper() != "SELL":
                continue
            stop = float(order.get("stopPrice", 0) or 0)
            if stop > 0 and current_price < stop * (1.0 - max(0.0, gap_tolerance_pct)):
                breached.append(order)
        if not breached:
            return False
        seen_lists = {int(item["orderListId"]) for item in breached if item.get("orderListId") is not None}
        for list_id in seen_lists:
            dependencies.cancel_oco(symbol, list_id)
        dependencies.sleep(0.2)
        base, _ = dependencies.get_symbol_assets(symbol)
        balances = dependencies.get_balances() or {}
        free = float((balances.get(base) or {}).get("free", 0) or 0)
        qty = dependencies.round_quantity(symbol, max(0.0, free - dependencies.min_quantity(symbol, 0)))
        if qty <= 0:
            dependencies.halt("gap below STOP_LIMIT: no free quantity after OCO cancel", symbol=symbol)
            return False
        result = dependencies.place_market_order(symbol, "SELL", qty) if dependencies.place_market_order else None
        if not result:
            dependencies.halt("gap below STOP_LIMIT: MARKET flatten not confirmed", symbol=symbol)
            return False
        dependencies.logger(f"[GAP-FLATTEN] {symbol} MARKET SELL qty={qty}")
        return True
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        dependencies.halt(f"gap watchdog failed: {exc}", symbol=symbol)
        return False


class BreakevenStateStore:
    """JSON-хранилище связи orderListId с исходной средней ценой BUY."""

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
) -> List[int]:
    """Защитить terminal/FILLED BUY и вернуть ещё не завершённые orderId."""
    remaining = list(order_ids)
    for order_id in list(remaining):
        order = dependencies.get_order(symbol, order_id)
        if not order:
            continue
        status = str(order.get("status", "")).upper()
        try:
            executed_status = float(order.get("executedQty", "0") or 0.0)
        except (TypeError, ValueError):
            executed_status = 0.0
        terminal_partial = (
            status in TERMINAL_EXCHANGE_STATES and executed_status > 0
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
            if executed_status <= 0:
                remaining.remove(order_id)
                continue

            cumulative_quote = float(
                order.get("cummulativeQuoteQty", "0") or 0.0
            )
            average_fill_price = cumulative_quote / executed_status
            if average_fill_price <= 0:
                average_fill_price = float(order.get("price", "0") or 0.0)

            tp_limit, sl_stop, sl_limit = dependencies.pick_oco_prices(
                symbol,
                ladder_prices,
                average_fill_price,
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
            except Exception:
                average_position = None
            if average_position is not None:
                minimum_guard: Optional[float] = None
                if panic_active:
                    if config.panic_sell_floor_pct is not None:
                        minimum_guard = average_position * (
                            1.0
                            - max(0.0, float(config.panic_sell_floor_pct))
                        )
                else:
                    minimum_guard = max(
                        average_position,
                        average_fill_price
                        * (1.0 + dependencies.profit_floor_pct()),
                    )
                if minimum_guard is not None and tp_limit < minimum_guard:
                    guard_floor = dependencies.round_price(
                        symbol, minimum_guard
                    )
                    if guard_floor > tp_limit:
                        dependencies.debugger(
                            f"[GUARD] {symbol} TP поднят: "
                            f"{dependencies.format_price(symbol, tp_limit)} → "
                            f"{dependencies.format_price(symbol, guard_floor)} "
                            f"(avg={dependencies.format_price(symbol, average_position)})"
                        )
                        tp_limit = guard_floor

            dependencies.pull_filters(symbol)
            base, _ = dependencies.get_symbol_assets(symbol)
            balances = dependencies.get_balances()
            base_free = float(
                balances.get(base, {}).get("free", 0.0)
            )
            dust = dependencies.min_quantity(symbol, 0)
            sellable = max(0.0, base_free - dust)
            quantity = dependencies.round_quantity(
                symbol, min(executed_status, sellable)
            )

            tp_rounded = dependencies.round_price(symbol, tp_limit)
            sl_rounded = dependencies.round_price(symbol, sl_limit)
            min_tp = dependencies.min_notional(symbol, tp_rounded)
            min_sl = dependencies.min_notional(symbol, sl_rounded)
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

            lot_id = dependencies.lot_id_for_fill(symbol, average_fill_price, order_id) if dependencies.lot_id_for_fill else None
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
                reason = "OCO не создан: fallback prefer-tp1 запрещён в LIVE (позиция без стопа)"
                try:
                    if dependencies.place_market_order is not None:
                        dependencies.place_market_order(symbol, "SELL", quantity)
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
                except Exception as exc:
                    dependencies.logger(
                        f"[FALLBACK-ERR] {symbol} -> {exc}"
                    )

            if oco and breakeven_enabled:
                try:
                    order_list_id = int(oco.get("orderListId") or 0)
                    if order_list_id:
                        state = state_store.load(symbol)
                        state[str(order_list_id)] = {
                            "fill_price": float(average_fill_price),
                            "tp_price": float(tp_rounded),
                            "ts": dependencies.now(),
                        }
                        state_store.save(symbol, state)
                        dependencies.debugger(
                            f"[BE] state add: orderListId={order_list_id} "
                            f"fill={dependencies.format_price(symbol, average_fill_price)}"
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
            dependencies.logger(
                f"[ATTACH-OCO-ERR] {symbol} order {order_id}: {exc}"
            )
            dependencies.halt(
                f"protection error for filled BUY {order_id}: {exc}",
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
    """Подтянуть SL к breakeven после частичного исполнения TP."""
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
                original = float(take_profit.get("origQty", "0") or 0.0)
                executed = float(
                    take_profit.get("executedQty", "0") or 0.0
                )
                remaining = max(0.0, original - executed)
            except (TypeError, ValueError):
                continue
            if executed <= 0 or remaining <= 0:
                continue

            fill_price = float(
                state.get(str(order_list_id), {}).get("fill_price", 0.0)
            )
            if fill_price <= 0:
                continue
            target_stop = dependencies.round_price(
                symbol, fill_price * (1.0 + offset_pct)
            )
            try:
                current_stop = float(
                    stop_loss.get("stopPrice", "0") or 0.0
                )
            except (TypeError, ValueError):
                current_stop = 0.0
            if current_stop + 1e-12 >= target_stop:
                continue

            dependencies.pull_filters(symbol)
            tick = dependencies.tick_size(symbol)
            epsilon = max(
                tick * max(1.0, dependencies.price_eps_mult()),
                fill_price * max(0.0, float(stop_limit_offset_pct)),
            )
            sl_stop = dependencies.round_step(target_stop, tick, "up")
            sl_limit = dependencies.round_step(
                sl_stop - epsilon, tick, "down"
            )
            if sl_stop <= sl_limit:
                sl_stop = dependencies.round_step(
                    sl_limit + tick, tick, "up"
                )
            try:
                tp_price = float(take_profit.get("price", "0") or 0.0)
            except (TypeError, ValueError):
                tp_price = 0.0
            if tp_price <= 0:
                continue

            remaining = dependencies.round_quantity(symbol, remaining)
            if remaining < dependencies.min_quantity(symbol, 0):
                dependencies.debugger(
                    f"[BE] skip dust remain="
                    f"{dependencies.format_quantity(symbol, remaining)}"
                )
                continue
            min_tp = dependencies.min_notional(symbol, tp_price)
            min_sl = dependencies.min_notional(symbol, sl_limit)
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
            except Exception:
                pass
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
                    "fill_price": float(fill_price),
                    "tp_price": float(tp_price),
                    "ts": dependencies.now(),
                }
                state_store.save(symbol, state)
                dependencies.logger(
                    f"[BE] {symbol} OCO re-arm -> BE stop="
                    f"{dependencies.format_price(symbol, sl_stop)} "
                    f"(orderListId={new_order_list_id})"
                )
    except Exception as exc:
        dependencies.debugger(f"[BE] loop err: {exc}")
