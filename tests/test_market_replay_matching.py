# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify price-through, cancellation and throttling replay semantics.
"""Focused market replay matching regressions."""

from decimal import Decimal

from ladder_dragon.strategy.market_replay import (
    BookLevel,
    MarketEvent,
    OrderBookReplay,
    ReplayOrder,
)


def _book(ts_ms: int) -> MarketEvent:
    return MarketEvent(
        ts_ms,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
    )


def test_better_resting_maker_fills_when_public_trade_passes_its_price():
    replay = OrderBookReplay(maker_fee_pct=Decimal("0.001"))
    assert replay.submit(
        ReplayOrder("inside", "BUY", Decimal("100.5"), Decimal("1"), 0),
        0,
    )
    assert replay.process(_book(1)) == []

    fills = replay.process(
        MarketEvent(
            2,
            bids=(BookLevel(Decimal("100"), Decimal("2")),),
            asks=(BookLevel(Decimal("101"), Decimal("2")),),
            trades=((Decimal("100"), Decimal("1"), "SELL"),),
        )
    )

    assert [(fill.order_id, fill.price, fill.liquidity) for fill in fills] == [
        ("inside", Decimal("100.5"), "MAKER")
    ]
    assert fills[0].fee_quote == Decimal("0.1005")


def test_public_trade_that_does_not_reach_limit_cannot_fill_maker():
    replay = OrderBookReplay()
    assert replay.submit(
        ReplayOrder("below", "BUY", Decimal("99.5"), Decimal("1"), 0),
        0,
    )
    replay.process(_book(1))

    assert replay.process(
        MarketEvent(
            2,
            trades=((Decimal("100"), Decimal("5"), "SELL"),),
        )
    ) == []


def test_cancel_latency_leaves_order_fillable_until_exchange_arrival():
    replay = OrderBookReplay(latency_ms=100)
    order = ReplayOrder("pending-cancel", "BUY", Decimal("100"), Decimal("1"), 0)
    assert replay.submit(order, 0, queue_ahead=Decimal("0"))
    replay.process(_book(100))
    assert replay.cancel(order.order_id, 110)

    fills = replay.process(
        MarketEvent(
            150,
            trades=((Decimal("100"), Decimal("1"), "SELL"),),
        )
    )

    assert [fill.order_id for fill in fills] == ["pending-cancel"]
    assert order.remaining == Decimal("0")


def test_cancel_becomes_effective_after_symmetric_latency():
    replay = OrderBookReplay(latency_ms=100)
    order = ReplayOrder("cancelled", "BUY", Decimal("100"), Decimal("1"), 0)
    assert replay.submit(order, 0, queue_ahead=Decimal("0"))
    replay.process(_book(100))
    assert replay.cancel(order.order_id, 110)

    assert replay.process(
        MarketEvent(
            210,
            trades=((Decimal("100"), Decimal("1"), "SELL"),),
        )
    ) == []
    assert order.cancelled is True
    assert order.remaining == Decimal("1")


def test_cancel_handoff_never_counts_shared_public_queue_twice():
    replay = OrderBookReplay()
    first = ReplayOrder("first", "BUY", Decimal("100"), Decimal("1"), 0)
    second = ReplayOrder("second", "BUY", Decimal("100"), Decimal("1"), 0)
    assert replay.submit(first, 0, queue_ahead=Decimal("2"))
    assert replay.submit(second, 0, queue_ahead=Decimal("2"))
    replay.process(_book(1))

    assert first.queue_ahead == Decimal("2")
    assert second.queue_ahead == Decimal("0")
    assert replay.cancel(first.order_id, 2)
    assert second.queue_ahead == Decimal("2")

    fills = replay.process(
        MarketEvent(
            3,
            trades=((Decimal("100"), Decimal("3"), "SELL"),),
        )
    )
    assert [(fill.order_id, fill.quantity) for fill in fills] == [
        ("second", Decimal("1"))
    ]


def test_rate_limit_returns_rejection_without_mutating_replay():
    replay = OrderBookReplay(max_requests_per_minute=1)
    first = ReplayOrder("first", "BUY", Decimal("100"), Decimal("1"), 0)
    rejected = ReplayOrder("rejected", "BUY", Decimal("100"), Decimal("1"), 0)
    assert replay.submit(first, 0)

    assert replay.submit(rejected, 1) is False
    assert rejected not in replay.orders
    assert replay.cancel(first.order_id, 2) is False
    assert first.cancel_effective_ts is None
    assert first.cancelled is False
