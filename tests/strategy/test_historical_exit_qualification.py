from dataclasses import replace
from decimal import Decimal as D
import runpy

import pytest

from ladder_dragon.strategy.market_replay import BookLevel


def fixture():
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    event = h["event"]
    x = h["HistoricalExecution"](event(3000), h["HistoricalPolicy"].parse(h["policy"]()), h["context"](), "exit")
    x.process(event(3200), veto=False, panic=False)
    x.process(event(3300, trades=((str(x.entry), str(x.quantity), "SELL"),)), veto=False, panic=False)
    return x, event


def test_stop_activation_has_no_second_transport_delay():
    x, event = fixture()
    x.process(event(3500, bid="98.4", ask="98.5", trades=((str(x.trigger), "0.01", "SELL"),)), veto=False, panic=False)
    assert x.order("target").cancelled
    assert x.order("stop").created_ts == 3501
    assert x.exit_qty == 0
    x.process(event(3501, bid="98.4", ask="98.5"), veto=False, panic=False)
    assert x.exit_qty == x.entry_qty


def test_stop_cannot_activate_before_protection_arrives():
    x, event = fixture()
    x.process(event(3350, bid="98.4", ask="98.5", trades=((str(x.trigger), "0.01", "SELL"),)), veto=False, panic=False)
    assert x.order("stop") is None


def test_thin_liquidation_retains_residual_and_censors_profit():
    x, event = fixture()
    thin = replace(event(3500, bid="90", ask="91"), bids=(BookLevel(D("90"), D("0.001")),))
    result = x.process(thin, veto=False, panic=True)
    assert x.exit_qty == D("0.001")
    assert result["unresolved_quantity"] == "1.004"
    assert result["censored"] and result["net_pnl_quote"] is None
    assert result["eligible_for_promotion"] is False
    before = x.exit_proceeds
    assert x.process(event(3600), veto=False, panic=True) == result
    assert x.flatten(thin, "PANIC_FLATTEN") == result
    assert x.exit_proceeds == before


def test_liquidation_consumes_multiple_levels_and_exact_fees():
    x, event = fixture()
    book = replace(event(3500, bid="90", ask="91"), bids=(BookLevel(D("90"), D("0.5")), BookLevel(D("80"), D("1"))))
    result = x.process(book, veto=False, panic=True)
    proceeds = (D("90") * D("0.5") + D("80") * D("0.505")) * D("0.999")
    assert x.exit_proceeds == proceeds and not result["censored"]
    assert x.fees == x.entry_cost * D("0.001") + proceeds * D("0.001")


def test_same_event_stop_liquidity_cannot_be_reused_for_flatten():
    x, event = fixture()
    x.process(event(3500, bid="98.4", ask="98.5", trades=((str(x.trigger), "0.01", "SELL"),)), veto=False, panic=False)
    thin = replace(event(3501, bid="98.4", ask="98.5"), bids=(BookLevel(D("98.4"), D("0.4")),))
    result = x.process(thin, veto=False, panic=True)
    assert x.exit_qty == D("0.4")
    assert result["censored"] and D(result["unresolved_quantity"]) == D("0.605")


def test_public_sell_trade_capacity_is_not_reused_by_flatten():
    x, event = fixture()
    thin = replace(event(3500, bid="90", ask="91", trades=(("90", "0.4", "SELL"),)),
                   bids=(BookLevel(D("90"), D("0.5")),))
    result = x.process(thin, veto=False, panic=True)
    assert x.exit_qty == D("0.1") and result["censored"]


@pytest.mark.parametrize("levels", [
    (("90", "-1"),), (("NaN", "1"),), (("90", "1"), ("91", "1")),
    (("90", "1"), ("90", "1")),
])
def test_invalid_liquidation_depth_blocks(levels):
    x, event = fixture()
    bad = replace(event(3500), bids=tuple(BookLevel(D(p), D(q)) for p, q in levels))
    with pytest.raises(ValueError):
        x.flatten(bad, "PANIC_FLATTEN")
    assert x.exit_qty == 0
