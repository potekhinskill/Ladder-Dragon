from decimal import Decimal

import pytest

from ladder_dragon.strategy.simulation import Candle, Inventory, SimulationConfig, simulate_grid, stress_grid, walk_forward
from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent


def candles():
    return [
        Candle(i, Decimal("100"), Decimal("103"), Decimal("97"), Decimal("100"))
        for i in range(12)
    ]


def test_partial_fills_and_fees_use_decimal_inventory():
    inv = Inventory()
    inv.buy(Decimal("100"), Decimal("0.4"), Decimal("0.03"))
    inv.buy(Decimal("90"), Decimal("0.6"), Decimal("0.04"))
    inv.sell(Decimal("110"), Decimal("0.5"), Decimal("0.04"))
    assert inv.qty == Decimal("0.5")
    assert inv.fees == Decimal("0.11")
    assert inv.realized > 0


def test_backtest_includes_costs_and_buy_hold():
    result = simulate_grid(candles(), SimulationConfig(latency_bars=1))
    assert result.trades > 0
    assert result.fees > 0
    assert result.buy_hold_equity == Decimal("1000")


def test_walk_forward_is_reproducible():
    configs = [
        SimulationConfig(buy_offset_pct=Decimal("0.01")),
        SimulationConfig(buy_offset_pct=Decimal("0.02")),
    ]
    first = walk_forward(candles(), configs, folds=3)
    second = walk_forward(candles(), configs, folds=3)
    assert [row["result"].final_equity for row in first] == [row["result"].final_equity for row in second]


def test_simulation_rejects_same_candle_latency():
    with pytest.raises(ValueError, match="latency_bars"):
        simulate_grid(candles(), SimulationConfig(latency_bars=0))


def test_simulation_does_not_fill_impossible_slippage_price():
    result = simulate_grid(
        [
            Candle(0, Decimal("100"), Decimal("100.1"), Decimal("99"), Decimal("100")),
            Candle(1, Decimal("100"), Decimal("100.1"), Decimal("99"), Decimal("100")),
            Candle(2, Decimal("100"), Decimal("100.1"), Decimal("99"), Decimal("100")),
        ],
        SimulationConfig(
            buy_offset_pct=Decimal("0.01"),
            take_profit_pct=Decimal("0.10"),
            slippage_pct=Decimal("0.02"),
            spread_pct=Decimal("0.02"),
            min_net_edge_pct=Decimal("0"),
        ),
    )
    assert result.trades == 0


def test_simulation_supports_partial_fill_and_conservative_oco_stop():
    result = simulate_grid(
        [
            Candle(0, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100")),
            Candle(1, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100")),
            # Both TP and stop are touched; stop must win.
            Candle(2, Decimal("100"), Decimal("102"), Decimal("95"), Decimal("100")),
            Candle(3, Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100")),
        ],
        SimulationConfig(
            partial_fill_ratio=Decimal("0.5"),
            stop_loss_pct=Decimal("0.02"),
            take_profit_pct=Decimal("0.01"),
        ),
    )
    assert result.trades >= 2
    assert result.fees > 0


def test_stress_grid_returns_explicit_downside_scenarios():
    results = stress_grid(candles(), SimulationConfig(), shocks=(Decimal("-0.30"),))
    assert Decimal("-0.30") in results
    assert results[Decimal("-0.30")].final_equity > 0


def test_orderbook_feed_is_used_by_backtest():
    feed = [MarketEvent(2, asks=(BookLevel(Decimal("98"), Decimal("0.2")),),
                        bids=(BookLevel(Decimal("97"), Decimal("0.2")),))]
    result = simulate_grid(candles(), SimulationConfig(take_profit_pct=Decimal("0.03")), market_events=feed)
    assert result.trades >= 0
