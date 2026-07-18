# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor planning component of the execution layer.
"""Чистые примитивы планирования BUY/SELL для символьного исполнителя.

Модуль ничего не знает о Binance HTTP и не меняет баланс. Он только строит
план; фактический расход средств происходит после подтверждённого размещения.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence


RoundValue = Callable[[float], float]


@dataclass(frozen=True)
class PlannedOrder:
    """Округлённый план одной заявки без побочных эффектов."""
    price: float
    quantity: float

    @property
    def notional(self) -> float:
        return self.price * self.quantity


def existing_prices(
    orders: Iterable[Mapping[str, object]],
    *,
    side: str,
    now_price: float,
    round_price: RoundValue,
) -> set[float]:
    """Собрать занятые цены нужной стороны в биржевой тиковой сетке."""
    result: set[float] = set()
    normalized_side = side.upper()
    for order in orders:
        try:
            if str(order.get("side", "")).upper() != normalized_side:
                continue
            if normalized_side == "SELL":
                order_type = str(order.get("type", "")).upper()
                if order_type not in (
                    "LIMIT",
                    "LIMIT_MAKER",
                    "STOP_LOSS_LIMIT",
                    "TAKE_PROFIT_LIMIT",
                ):
                    continue
            price = float(order.get("price") or 0.0)
            if price <= 0:
                continue
            if normalized_side == "BUY" and price >= now_price:
                continue
            if normalized_side == "SELL" and price <= now_price:
                continue
            result.add(round_price(price))
        except (TypeError, ValueError):
            continue
    return result


def buy_candidates(
    ladder_prices: Sequence[float],
    *,
    now_price: float,
    occupied_prices: set[float],
    round_price: RoundValue,
    limit: Optional[int],
) -> list[float]:
    """Выбрать незанятые уровни BUY строго ниже текущего рынка."""
    candidates = [
        price
        for price in ladder_prices
        if 0 < price < now_price and round_price(price) not in occupied_prices
    ]
    return candidates[:limit] if limit is not None else candidates


def plan_buy_order(
    price: float,
    *,
    free_quote: float,
    cap_per_order: float,
    remaining_slots: int,
    use_all_remaining: bool,
    min_order_notional: Optional[float],
    min_quantity: float,
    min_notional: float,
    round_price: RoundValue,
    round_quantity: RoundValue,
) -> Optional[PlannedOrder]:
    """Рассчитать один BUY в пределах CAP, баланса и биржевых минимумов."""
    rounded_price = round_price(price)
    if rounded_price <= 0 or free_quote <= 0:
        return None
    # Divide the remainder across remaining slots so early levels do not consume all cash.
    local_cap = min(
        cap_per_order,
        free_quote / max(1, remaining_slots),
    )
    if use_all_remaining:
        local_cap = free_quote

    quantity = round_quantity(local_cap / rounded_price)
    if quantity < min_quantity:
        quantity = min_quantity
    if quantity * rounded_price < min_notional:
        needed = round_quantity(max(min_notional / rounded_price, min_quantity))
        available_cap = free_quote if use_all_remaining else local_cap
        if needed * rounded_price > available_cap:
            return None
        quantity = needed

    if quantity * rounded_price > free_quote:
        quantity = round_quantity(max(0.0, free_quote / rounded_price))
    if quantity <= 0:
        return None

    order = PlannedOrder(price=rounded_price, quantity=quantity)
    if (
        min_order_notional is not None
        and order.notional < min_order_notional
    ):
        return None
    return order


def guarded_sell_levels(
    ladder_prices: Sequence[float],
    *,
    now_price: float,
    occupied_prices: set[float],
    round_price: RoundValue,
    limit: Optional[int],
    average_entry: Optional[float],
    panic_active: bool,
    panic_floor_pct: Optional[float],
    profit_floor_pct: float,
) -> list[float]:
    """Поднять SELL до допустимого floor и устранить дубли после округления."""
    candidates = [
        price
        for price in ladder_prices
        if price > now_price and round_price(price) not in occupied_prices
    ]
    if limit is not None:
        candidates = candidates[:limit]
    if not candidates:
        return []

    all_steps = sorted({round_price(price) for price in ladder_prices})
    upper_steps = sorted(
        {round_price(price) for price in ladder_prices if price > now_price}
    )
    guarded: list[float] = []
    for index, price in enumerate(candidates):
        minimum: Optional[float] = None
        if average_entry is not None:
            if panic_active and panic_floor_pct is not None:
                minimum = average_entry * (
                    1.0 - max(0.0, panic_floor_pct)
                )
            elif not panic_active:
                minimum = average_entry * (
                    1.0 + max(0.0, profit_floor_pct)
                )
        target = max(price, minimum) if minimum is not None else price
        if target != price:
            available = [step for step in all_steps if step >= target]
            bumped = (
                available[min(index, len(available) - 1)]
                if available
                else round_price(target)
            )
            if minimum is not None:
                bumped = max(bumped, minimum)
            target = bumped
        if target > now_price:
            guarded.append(target)

    # A guard can collapse several levels onto one tick. Push duplicates to
    # the next free step instead of creating identical SELL orders.
    result: list[float] = []
    seen: set[float] = set()
    for price in guarded:
        rounded = round_price(price)
        if rounded in seen:
            position = next(
                (
                    index
                    for index, step in enumerate(upper_steps)
                    if step >= rounded
                ),
                len(upper_steps),
            )
            while position < len(upper_steps) and upper_steps[position] in seen:
                position += 1
            if position >= len(upper_steps):
                continue
            rounded = upper_steps[position]
        if rounded <= now_price or rounded in seen:
            continue
        seen.add(rounded)
        result.append(rounded)
    return result


def plan_sell_orders(
    levels: Sequence[float],
    *,
    free_base: float,
    dust_quantity: float,
    min_quantity: float,
    min_notional_for_price: Callable[[float], float],
    round_quantity: RoundValue,
) -> list[PlannedOrder]:
    quantity_left = max(0.0, free_base - dust_quantity)
    if quantity_left <= 0 or not levels:
        return []
    share = quantity_left / len(levels)
    result: list[PlannedOrder] = []
    for index, price in enumerate(levels, start=1):
        quantity = min(share, quantity_left)
        needed = round_quantity(
            max(min_notional_for_price(price) / price, min_quantity)
        )
        if quantity < needed:
            quantity = min(needed, quantity_left)
        quantity = round_quantity(quantity)
        if index == len(levels):
            quantity = round_quantity(quantity_left)
        if quantity > quantity_left:
            quantity = round_quantity(quantity_left)
        if (
            quantity <= 0
            or quantity * price < min_notional_for_price(price)
        ):
            continue
        result.append(PlannedOrder(price=price, quantity=quantity))
        quantity_left = max(0.0, quantity_left - quantity)
    return result


def plan_sell_order(
    price: float,
    *,
    quantity_left: float,
    share: float,
    is_last: bool,
    min_quantity: float,
    min_notional: float,
    round_quantity: RoundValue,
) -> Optional[PlannedOrder]:
    """Спланировать SELL, не уменьшая inventory до получения ACK вызывающим кодом."""
    if price <= 0 or quantity_left <= 0:
        return None
    quantity = min(share, quantity_left)
    needed = round_quantity(max(min_notional / price, min_quantity))
    if quantity < needed:
        quantity = min(needed, quantity_left)
    quantity = round_quantity(quantity)
    if is_last:
        quantity = round_quantity(quantity_left)
    if quantity > quantity_left:
        quantity = round_quantity(quantity_left)
    if quantity <= 0 or quantity * price < min_notional:
        return None
    return PlannedOrder(price=price, quantity=quantity)
