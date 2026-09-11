from decimal import Decimal as D
import json
import random

import pytest

from ladder_dragon.strategy.depth_segments import PublicBook
from ladder_dragon.strategy.indexed_book import IndexedBookSide
from ladder_dragon.strategy.market_replay import BookLevel


def test_random_updates_match_dictionary_sort_exactly():
    rng = random.Random(340)
    side = IndexedBookSide(); reference = {}
    for _ in range(2000):
        price = D(rng.randrange(1, 150)); quantity = D(rng.randrange(0, 100)) / 10
        if quantity:
            side[price] = quantity; reference[price] = quantity
        else:
            side.pop(price, None); reference.pop(price, None)
        for descending in (False, True):
            for limit in (1, 10, 1000):
                expected = tuple(BookLevel(p, q) for p, q in sorted(reference.items(), reverse=descending)[:limit])
                assert side.view(limit, descending=descending) == expected
        assert dict(side) == reference
    side.clear(); assert side.view(10, descending=False) == ()


def test_decimal_representation_and_prior_views_survive_updates():
    side = IndexedBookSide(); side[D('1.00')] = D('2.00')
    previous = side.view(2, descending=False)
    side[D('1.0')] = D('2.0')
    current = side.view(2, descending=False)
    assert str(current[0].price) == '1.00'
    assert str(current[0].quantity) == '2.0'
    assert str(previous[0].quantity) == '2.00'
    side[D('3')] = D('4'); del side[D('1')]
    assert previous == (BookLevel(D('1'), D('2')),)


def seed():
    return {'s':'SOLUSDT', '_received_at_ms':1, 'lastUpdateId':100,
            'bids':[['99','2'],['98','3']], 'asks':[['101','4'],['102','5']]}


def test_trade_reuses_levels_without_changing_snapshot_or_future_events():
    book = PublicBook(); first = book.apply(seed())
    trade = book.apply({'e':'aggTrade','a':1,'p':'100','q':'1','m':True,'_received_at_ms':2})
    assert first.bids is trade.bids and first.asks is trade.asks
    changed = book.apply({'e':'depthUpdate','U':101,'u':101,'b':[['99','0'],['98','7']], 'a':[], '_received_at_ms':3})
    assert changed.bids == (BookLevel(D('98'),D('7')),)
    assert first.bids[0].price == D('99')
    assert changed.asks is trade.asks
    snapshot = book.snapshot('SOLUSDT')
    carried = PublicBook(); assert carried.apply(snapshot) == PublicBook().apply(snapshot)
    assert json.dumps(carried.snapshot('SOLUSDT'),sort_keys=True)==json.dumps(snapshot,sort_keys=True)


@pytest.mark.parametrize('limit', [0,-1,20001,True,1.5])
def test_invalid_view_limit_fails_closed(limit):
    with pytest.raises(ValueError): PublicBook().apply(seed(),level_limit=limit)


def test_book_sequence_and_cross_checks_are_not_cached_away():
    book = PublicBook(); book.apply(seed())
    with pytest.raises(ValueError,match='sequence gap'):
        book.apply({'e':'depthUpdate','U':102,'u':102,'b':[], 'a':[], '_received_at_ms':2})
    with pytest.raises(ValueError,match='crossed'):
        book.apply({'e':'depthUpdate','U':101,'u':101,'b':[['102','1']], 'a':[], '_received_at_ms':2})
