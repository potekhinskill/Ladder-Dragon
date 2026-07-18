import json
from decimal import Decimal
from pathlib import Path

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent, OrderBookReplay, ReplayOrder
from ladder_dragon.execution.trade_accounting import TradeExecution, replay_average_cost


def test_recorded_like_lost_response_is_reconciled_from_query():
    fixture = json.loads(Path("tests/fixtures/binance_fills.json").read_text())
    order = fixture["lost_response_after_fill"]["query_response"]
    assert order["status"] == "FILLED"
    assert Decimal(order["executedQty"]) > 0


def test_partial_sell_bnb_fee_is_cash_cost_without_base_double_count():
    fixture = json.loads(Path("tests/fixtures/binance_fills.json").read_text())["bnb_partial_sell_fee"]
    buy = TradeExecution.create(symbol="SOLUSDT", side="BUY", price=100, gross_qty=1,
                                commission_asset="USDT", commission_amount=Decimal("0.1"), commission_quote=Decimal("0.1"))
    sell = TradeExecution.create(symbol="SOLUSDT", side="SELL", price=Decimal(fixture["price"]),
                                 gross_qty=Decimal(fixture["qty"]), commission_asset="BNB",
                                 commission_amount=Decimal(fixture["commission"]), commission_quote=Decimal("0.02"))
    result = replay_average_cost([buy, sell])
    assert result.realized_pnl > 0


def test_queue_trade_print_delays_fill_until_queue_is_consumed():
    replay = OrderBookReplay()
    replay.submit(ReplayOrder("x", "BUY", Decimal("100"), Decimal("1"), 0), 0,
                  queue_ahead=Decimal("2"))
    event = MarketEvent(1, asks=(BookLevel(Decimal("100"), Decimal("1")),),
                        trades=((Decimal("100"), Decimal("1"), "SELL"),))
    assert replay.process(event) == []
    event = MarketEvent(2, asks=(BookLevel(Decimal("100"), Decimal("1")),),
                        trades=((Decimal("100"), Decimal("1"), "SELL"),))
    assert replay.process(event)[0][0] == "x"
