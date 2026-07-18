from decimal import Decimal

import pytest

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent, OrderBookReplay, ReplayOrder


def test_price_time_priority_and_latency():
    replay = OrderBookReplay(latency_ms=100)
    replay.submit(ReplayOrder("late", "BUY", Decimal("10"), Decimal("1"), 0), 0)
    replay.submit(ReplayOrder("early", "BUY", Decimal("10"), Decimal("1"), 0), 0)
    event = MarketEvent(50, asks=(BookLevel(Decimal("10"), Decimal("2")),))
    assert replay.process(event) == []
    event = MarketEvent(100, asks=(BookLevel(Decimal("10"), Decimal("2")),))
    assert [fill[0] for fill in replay.process(event)] == ["late", "early"]


def test_cancel_and_rate_limit():
    replay = OrderBookReplay(max_requests_per_minute=2)
    order = ReplayOrder("x", "BUY", Decimal("10"), Decimal("1"), 0)
    replay.submit(order, 0)
    assert replay.cancel("x", 1)
    with pytest.raises(RuntimeError):
        replay.submit(ReplayOrder("y", "BUY", Decimal("10"), Decimal("1"), 0), 2)
