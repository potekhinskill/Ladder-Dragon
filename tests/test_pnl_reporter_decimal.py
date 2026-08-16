from decimal import Decimal

import pytest

from bin.pnl_reporter import fifo_pnl


def test_fifo_reporter_uses_exact_decimal_accounting():
    gross, fees, stats = fifo_pnl(
        [
            {
                "symbol": "SOLUSDT",
                "isBuyer": True,
                "qty": "0.30000000",
                "price": "10.10000000",
                "quoteQty": "3.03000000",
                "commission": "0.00030000",
                "commissionAsset": "SOL",
            },
            {
                "symbol": "SOLUSDT",
                "isBuyer": False,
                "qty": "0.10000000",
                "price": "11.10000000",
                "quoteQty": "1.11000000",
                "commission": "0.00111000",
                "commissionAsset": "USDT",
            },
        ]
    )

    assert gross == Decimal("0.1000000000000000")
    assert fees == Decimal("0.0041400000000000")
    assert stats["open_lots_qty"] == Decimal("0.19970000")


def test_fifo_reporter_uses_canonical_non_usdt_quote_assets():
    gross, fees, stats = fifo_pnl(
        [
            {
                "symbol": "ETHGBP",
                "isBuyer": True,
                "qty": "1",
                "price": "2000",
                "quoteQty": "2000",
                "commission": "2",
                "commissionAsset": "GBP",
            }
        ]
    )

    assert gross == Decimal("0")
    assert fees == Decimal("2")
    assert stats["third_asset_fees_units"] == Decimal("0")


def test_fifo_reporter_rejects_an_unknown_quote_without_guessing():
    with pytest.raises(ValueError, match="cannot determine assets"):
        fifo_pnl(
            [
                {
                    "symbol": "ABCXYZ",
                    "isBuyer": True,
                    "qty": "1",
                    "price": "1",
                    "quoteQty": "1",
                    "commission": "0",
                    "commissionAsset": "XYZ",
                }
            ]
        )
