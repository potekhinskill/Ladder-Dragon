# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compute one causal entry-veto signal for replay and live execution.
"""Shared rolling entry-veto signal with an exact window boundary."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from ladder_dragon.strategy.market_replay import MarketEvent


ZERO = Decimal("0")
TEN_THOUSAND = Decimal("10000")
MAXIMUM_SIGNAL_ROWS = 100_000
ENTRY_VETO_SIGNAL_CONTRACT = {
    "schema_version": 1,
    "event_population": "RECONSTRUCTED_SNAPSHOT_DEPTH_AND_AGGTRADE_V1",
    "window_boundary": "KEEP_LAST_PRE_WINDOW_BID_ANCHOR_EXCLUDE_ITS_FLOW_V1",
    "readiness": "FULL_WINDOW_WITH_POSITIVE_TRADE_AND_OFI_SCALE_V1",
    "reconnect_reset": "CLEAR_ALL_ROWS_TOTALS_AND_TOP_V1",
}


def top_of_book(
    event: MarketEvent,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return one validated best bid and ask tuple."""
    if not event.bids or not event.asks:
        raise ValueError("entry-veto signal requires both book sides")
    bid = max(event.bids, key=lambda level: level.price)
    ask = min(event.asks, key=lambda level: level.price)
    if bid.price <= ZERO or ask.price <= bid.price:
        raise ValueError("entry-veto signal book is invalid")
    return bid.price, bid.quantity, ask.price, ask.quantity


def order_flow_increment(
    previous: tuple[Decimal, Decimal, Decimal, Decimal],
    current: tuple[Decimal, Decimal, Decimal, Decimal],
) -> Decimal:
    """Return Cont-style best-level order-flow imbalance for one event."""
    old_bid, old_bid_qty, old_ask, old_ask_qty = previous
    bid, bid_qty, ask, ask_qty = current
    bid_flow = (
        bid_qty if bid > old_bid
        else -old_bid_qty if bid < old_bid
        else bid_qty - old_bid_qty
    )
    ask_flow = (
        -ask_qty if ask < old_ask
        else old_ask_qty if ask > old_ask
        else old_ask_qty - ask_qty
    )
    return bid_flow + ask_flow


@dataclass(frozen=True)
class EntryVetoSignal:
    """Expose one immutable rolling signal snapshot."""

    ready: bool
    price_change_bps: Decimal
    signed_trade_flow: Decimal
    order_flow_imbalance: Decimal
    trade_flow_quote: Decimal
    buy_quantity: Decimal
    sell_quantity: Decimal
    best_bid: Decimal
    best_ask: Decimal
    bid_quantity: Decimal
    ask_quantity: Decimal


class EntryVetoSignalAccumulator:
    """Consume each reconstructed public event once for replay and LIVE."""

    def __init__(self, window_ms: int, *, maximum_rows: int = MAXIMUM_SIGNAL_ROWS) -> None:
        if type(window_ms) is not int or window_ms < 100:
            raise ValueError("entry-veto signal window is invalid")
        if type(maximum_rows) is not int or not 1 <= maximum_rows <= MAXIMUM_SIGNAL_ROWS:
            raise ValueError("entry-veto signal capacity is invalid")
        self.window_ms = window_ms
        self.maximum_rows = maximum_rows
        self.reset()

    def reset(self) -> None:
        """Remove all connection-scoped observations."""
        self.rows: deque[
            tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]
        ] = deque()
        self.previous_top: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
        self.ofi = ZERO
        self.ofi_scale = ZERO
        self.buy_quantity = ZERO
        self.sell_quantity = ZERO
        self.trade_flow_quote = ZERO
        self.current_top = (ZERO, ZERO, ZERO, ZERO)

    def update(self, event: MarketEvent) -> EntryVetoSignal:
        """Update the exact trailing window at the event receive time."""
        current = top_of_book(event)
        increment = (
            order_flow_increment(self.previous_top, current)
            if self.previous_top is not None else ZERO
        )
        self.previous_top = current
        self.current_top = current
        buy = sell = signed_quote = ZERO
        for price, quantity, aggressor in event.trades:
            if aggressor == "BUY":
                buy += quantity
                signed_quote += price * quantity
            elif aggressor == "SELL":
                sell += quantity
                signed_quote -= price * quantity
        self.rows.append(
            (
                event.ts_ms, current[0], increment, abs(increment), buy, sell,
                signed_quote,
            )
        )
        if len(self.rows) > self.maximum_rows:
            raise ValueError("entry-veto signal capacity reached")
        self.ofi += increment
        self.ofi_scale += abs(increment)
        self.buy_quantity += buy
        self.sell_quantity += sell
        self.trade_flow_quote += signed_quote
        cutoff = event.ts_ms - self.window_ms
        while len(self.rows) > 1 and self.rows[1][0] <= cutoff:
            self._remove_contribution(self.rows.popleft())
        if self.rows and self.rows[0][0] < cutoff:
            anchor = self.rows[0]
            self._remove_contribution(anchor)
            self.rows[0] = (
                anchor[0], anchor[1], ZERO, ZERO, ZERO, ZERO, ZERO,
            )
        return self.snapshot()

    def _remove_contribution(
        self,
        row: tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal],
    ) -> None:
        _, _, ofi, scale, buy, sell, quote = row
        self.ofi -= ofi
        self.ofi_scale -= scale
        self.buy_quantity -= buy
        self.sell_quantity -= sell
        self.trade_flow_quote -= quote

    def snapshot(self) -> EntryVetoSignal:
        """Return the current signal without changing accumulator state."""
        bid, bid_quantity, ask, ask_quantity = self.current_top
        total = self.buy_quantity + self.sell_quantity
        ready = bool(
            self.rows
            and self.rows[-1][0] - self.rows[0][0] >= self.window_ms
            and total > ZERO
            and self.ofi_scale > ZERO
        )
        price_change = (
            (bid / self.rows[0][1] - Decimal("1")) * TEN_THOUSAND
            if self.rows and self.rows[0][1] > ZERO else ZERO
        )
        return EntryVetoSignal(
            ready=ready,
            price_change_bps=price_change,
            signed_trade_flow=(
                (self.buy_quantity - self.sell_quantity) / total
                if total > ZERO else ZERO
            ),
            order_flow_imbalance=(
                self.ofi / self.ofi_scale if self.ofi_scale > ZERO else ZERO
            ),
            trade_flow_quote=self.trade_flow_quote,
            buy_quantity=self.buy_quantity,
            sell_quantity=self.sell_quantity,
            best_bid=bid,
            best_ask=ask,
            bid_quantity=bid_quantity,
            ask_quantity=ask_quantity,
        )


__all__ = [
    "ENTRY_VETO_SIGNAL_CONTRACT",
    "EntryVetoSignal",
    "EntryVetoSignalAccumulator",
    "order_flow_increment",
    "top_of_book",
]
