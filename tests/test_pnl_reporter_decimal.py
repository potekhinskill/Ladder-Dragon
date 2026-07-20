from decimal import Decimal

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
