# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: share immutable event normalization, never mutable matching state.
"""Event-local derived views with independent copies for each matcher."""

from types import MappingProxyType


def _views(event):
    bids, asks = event.bids, event.asks
    cached = getattr(event, "_normalized_book_views", None)
    if cached is not None and cached[0] is bids and cached[1] is asks:
        return cached
    value = (
        bids, asks,
        MappingProxyType({level.price: level.quantity for level in bids}),
        MappingProxyType({level.price: level.quantity for level in asks}),
        max(bids, key=lambda level: level.price) if bids else None,
        min(asks, key=lambda level: level.price) if asks else None,
    )
    # Canonical events contain immutable tuples of frozen BookLevel values.
    # Mutable legacy populations must be recomputed, never cached by identity.
    if type(bids) is tuple and type(asks) is tuple:
        object.__setattr__(event, "_normalized_book_views", value)
    return value


def event_book(event):
    views = _views(event)
    return views[2], views[3]


def event_top(event):
    views = _views(event)
    return views[4], views[5]
