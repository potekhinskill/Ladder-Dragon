from decimal import Decimal as D, localcontext

import pytest

from ladder_dragon.execution.buy_settlement import settle_buy


def order():
    return dict(symbol="SOLUSDT", orderId=42, side="BUY", status="FILLED",
                origQty="1", executedQty="1", cummulativeQuoteQty="100")


def fill(**changes):
    return dict(symbol="SOLUSDT", orderId=42, id=1, isBuyer=True,
                price="100", qty="1", quoteQty="100", commission="0.001",
                commissionAsset="SOL") | changes


@pytest.mark.parametrize("asset,expected", [("SOL", "0.999"), ("USDT", "1"), ("BNB", "1")])
def test_fee_asset_controls_inventory_not_quote_valuation(asset, expected):
    result = settle_buy(order(), [fill(commissionAsset=asset)], symbol="SOLUSDT", order_id=42)
    assert result.net_quantity == D(expected)
    assert result.gross_quantity == D("1") and result.quote_quantity == D("100")


@pytest.mark.parametrize("change", [
    {"symbol": "ETHUSDT"}, {"orderId": 99}, {"orderId": True},
    {"isBuyer": "true"}, {"id": True}, {"commission": None},
    {"commissionAsset": ""}, {"commissionAsset": "UNKNOWN"}, {"commission": "NaN"},
    {"commission": "-0.1"}, {"qty": 1.0}, {"quoteQty": "99"},
    {"commission": "1"}, {"commission": "1e-40"},
])
def test_invalid_fill_blocks(change):
    with pytest.raises((ValueError, ArithmeticError)):
        settle_buy(order(), [fill(**change)], symbol="SOLUSDT", order_id=42)


def test_missing_and_duplicate_fills_cannot_prove_settlement():
    half = fill(qty="0.5", quoteQty="50")
    for rows in ([], [half], [half, half]):
        with pytest.raises(ValueError):
            settle_buy(order(), rows, symbol="SOLUSDT", order_id=42)


def test_mixed_fees_and_terminal_partial_are_exact_and_order_independent():
    terminal = order() | dict(status="CANCELED", executedQty="0.5", cummulativeQuoteQty="50")
    rows = [fill(qty="0.2", quoteQty="20"),
            fill(id=2, qty="0.3", quoteQty="30", commissionAsset="USDT")]
    first = settle_buy(terminal, rows, symbol="SOLUSDT", order_id=42)
    second = settle_buy(terminal, list(reversed(rows)), symbol="SOLUSDT", order_id=42)
    assert first == second and first.net_quantity == D("0.499")


def test_nonterminal_order_cannot_authorize_settlement():
    with pytest.raises(ValueError):
        settle_buy(order() | {"status": "PARTIALLY_FILLED"}, [fill()], symbol="SOLUSDT", order_id=42)


def test_small_fee_survives_low_ambient_precision():
    with localcontext() as ambient:
        ambient.prec = 4
        result = settle_buy(order(), [fill(commission="0." + "0" * 39 + "1")],
                            symbol="SOLUSDT", order_id=42)
        assert result.net_quantity == D("0." + "9" * 40)
        assert ambient.prec == 4


def test_tiny_excess_fill_cannot_round_into_complete_coverage():
    tiny = "0." + "0" * 39 + "1"
    rows = [fill(commission="0"), fill(id=2, qty=tiny, price="1", quoteQty=tiny, commission="0")]
    with pytest.raises(ValueError, match="do not cover"):
        settle_buy(order(), rows, symbol="SOLUSDT", order_id=42)
