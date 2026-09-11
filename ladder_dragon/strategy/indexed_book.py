# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve exact public levels without sorting each event again.
"""An in-memory price index with immutable bounded book views."""

from bisect import bisect_left, insort
from collections.abc import MutableMapping
from decimal import Decimal

from ladder_dragon.strategy.market_replay import BookLevel


class IndexedBookSide(MutableMapping):
    """Keep one sorted price index and reuse unchanged immutable levels."""

    def __init__(self):
        self._levels: dict[Decimal, BookLevel] = {}
        self._prices: list[Decimal] = []
        self._view_key: tuple[int, bool] | None = None
        self._view: tuple[BookLevel, ...] = ()

    def __getitem__(self, price):
        return self._levels[price].quantity

    def __setitem__(self, price, quantity):
        previous = self._levels.get(price)
        if previous is not None and previous.quantity.as_tuple() == quantity.as_tuple():
            return
        if previous is None:
            insort(self._prices, price)
        self._levels[price] = BookLevel(previous.price if previous is not None else price, quantity)
        self._view_key = None

    def __delitem__(self, price):
        del self._levels[price]
        del self._prices[bisect_left(self._prices, price)]
        self._view_key = None

    def __iter__(self):
        return iter(self._prices)

    def __len__(self):
        return len(self._levels)

    def clear(self):
        self._levels.clear()
        self._prices.clear()
        self._view_key = None
        self._view = ()

    def best_price(self, *, descending: bool):
        return self._prices[-1 if descending else 0]

    def view(self, limit: int, *, descending: bool) -> tuple[BookLevel, ...]:
        key = (limit, descending)
        if key != self._view_key:
            prices = self._prices[-limit:][::-1] if descending else self._prices[:limit]
            self._view = tuple(self._levels[price] for price in prices)
            self._view_key = key
        return self._view
