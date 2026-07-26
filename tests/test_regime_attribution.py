from decimal import Decimal

import pytest

from ladder_dragon.execution.trade_accounting import TradeExecution
from ladder_dragon.strategy.regime_attribution import (
    RegimeSnapshot,
    TimedExecution,
    attribute_fifo_by_regime,
)


def trade(side, price, quantity):
    return TradeExecution.create(
        symbol="SOLUSDT",
        side=side,
        price=price,
        gross_qty=quantity,
        net_qty=quantity,
        commission_quote="0",
    )


def test_regime_report_compares_exact_fifo_to_hold_and_usdt():
    results = attribute_fifo_by_regime(
        [
            TimedExecution(1000, trade("BUY", "100", "1")),
            TimedExecution(2000, trade("SELL", "110", "1")),
        ],
        [
            RegimeSnapshot(
                "SOLUSDT", 900, "RANGE", Decimal("100")
            ),
            RegimeSnapshot(
                "SOLUSDT", 2900, "TREND_UP", Decimal("120")
            ),
        ],
        window_start_ms=0,
        window_end_ms=3000,
        end_prices={"SOLUSDT": Decimal("120")},
        benchmark_exit_fee_pct=Decimal("0.001"),
        max_snapshot_age_ms=500,
        fill_observations={"RANGE": (3, 4)},
    )

    ranged = results[0]
    assert ranged.regime == "RANGE"
    assert ranged.strategy_net_pnl == Decimal("10")
    assert ranged.buy_hold_net_pnl == Decimal("19.880")
    assert ranged.usdt_pnl == Decimal("0")
    assert ranged.samples == 1
    assert ranged.fill_rate == Decimal("0.75")
    assert ranged.candidate_samples == 4


def test_regime_report_blocks_stale_or_future_context():
    with pytest.raises(ValueError, match="missing past|stale"):
        attribute_fifo_by_regime(
            [
                TimedExecution(1000, trade("BUY", "100", "1")),
                TimedExecution(2000, trade("SELL", "110", "1")),
            ],
            [
                RegimeSnapshot(
                    "SOLUSDT", 1100, "RANGE", Decimal("100")
                )
            ],
            window_start_ms=0,
            window_end_ms=3000,
            end_prices={"SOLUSDT": Decimal("120")},
            benchmark_exit_fee_pct=Decimal("0.001"),
            max_snapshot_age_ms=500,
        )
