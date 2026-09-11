from dataclasses import asdict
from decimal import Decimal as D
import importlib.util
from pathlib import Path
import random
import pytest

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent, OrderBookReplay, ReplayOrder
from ladder_dragon.strategy.replay_event_book import event_book, event_top
from ladder_dragon.strategy.entry_veto_signal import top_of_book


def test_views_preserve_duplicate_and_unsorted_level_semantics():
    bids = (BookLevel(D('2'), D('3')), BookLevel(D('1'), D('4')), BookLevel(D('2'), D('5')))
    event = MarketEvent(1, bids, (BookLevel(D('3'), D('6')),))
    assert event_top(event)[0] == bids[0]
    assert event_book(event)[0][D('2')] == D('5')
    with pytest.raises(TypeError): event_book(event)[0][D('2')] = D('999')
    copy = event_book(event)[0].copy(); copy.clear()
    assert event_book(event)[0][D('2')] == D('5')
    assert top_of_book(event) == (D('2'), D('3'), D('3'), D('6'))


def test_mutable_legacy_levels_are_not_cached():
    bids = [BookLevel(D('1'),D('2'))]
    event = MarketEvent(1, bids, [BookLevel(D('3'),D('4'))])
    assert event_top(event)[0].price == D('1')
    bids[0] = BookLevel(D('2'),D('5'))
    assert event_top(event)[0].price == D('2')


@pytest.mark.parametrize('seed', range(8))
def test_matching_is_identical_to_published_v339(seed):
    path = Path(__file__).parents[1] / 'fixtures/replay_process_v339.py'
    spec = importlib.util.spec_from_file_location('reference_matcher',path)
    reference = importlib.util.module_from_spec(spec); spec.loader.exec_module(reference)
    class Baseline(OrderBookReplay):
        process = reference.process
    rng = random.Random(seed)
    old, new = Baseline(latency_ms=2, market_impact_bps=D('3')), OrderBookReplay(latency_ms=2, market_impact_bps=D('3'))
    for tick in range(200):
        if tick % 7 == 0:
            side = rng.choice(['BUY','SELL']); price = D(rng.randrange(98,104)); qty = D(rng.randrange(1,6))
            for matcher in [old,new]: matcher.submit(ReplayOrder(str(tick),side,price,qty,tick),tick)
        if tick % 11 == 0:
            for matcher in [old,new]: matcher.cancel(str(max(0,tick-7)),tick)
        event = MarketEvent(tick, tuple(BookLevel(D(p),D(rng.randrange(1,8))) for p in [99,98,97]),
                            tuple(BookLevel(D(p),D(rng.randrange(1,8))) for p in [101,102,103]),
                            ((D(rng.randrange(97,104)),D(rng.randrange(1,10)),rng.choice(['BUY','SELL'])),))
        assert old.process(event) == new.process(event)
        assert [asdict(o) for o in old.orders] == [asdict(o) for o in new.orders]
        assert old._previous_bids == new._previous_bids
        assert old._previous_asks == new._previous_asks
