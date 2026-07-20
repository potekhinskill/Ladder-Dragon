from decimal import Decimal

import pytest

from ladder_dragon.execution.exchange_filters import validate_sell_percent_prices


def exchange_info(*, ask_down="0.8", ask_up="5"):
    return {
        "symbols": [{
            "symbol": "SOLUSDT",
            "filters": [{
                "filterType": "PERCENT_PRICE_BY_SIDE",
                "askMultiplierDown": ask_down,
                "askMultiplierUp": ask_up,
            }],
        }]
    }


def test_sell_percent_by_side_accepts_prices_inside_exact_decimal_band():
    assert validate_sell_percent_prices(
        exchange_info(), symbol="SOLUSDT", reference_price=Decimal("100"),
        prices=[Decimal("80"), Decimal("500")],
    )


def test_sell_percent_by_side_fails_closed_outside_band():
    with pytest.raises(RuntimeError, match="outside Binance"):
        validate_sell_percent_prices(
            exchange_info(), symbol="SOLUSDT", reference_price="100",
            prices=["500.01"],
        )


def test_sell_percent_by_side_rejects_missing_symbol_metadata():
    with pytest.raises(RuntimeError, match="exactly one"):
        validate_sell_percent_prices(
            {"symbols": []}, symbol="SOLUSDT", reference_price="100",
            prices=["101"],
        )
