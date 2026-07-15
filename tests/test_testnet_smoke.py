from decimal import Decimal

import pytest

from binance_testnet_smoke import build_non_filling_limit_buy, validate_testnet_base


def test_smoke_client_refuses_mainnet_and_lookalike_hosts():
    with pytest.raises(ValueError):
        validate_testnet_base("https://api.binance.com")
    with pytest.raises(ValueError):
        validate_testnet_base("https://testnet.binance.vision.attacker.example")
    assert validate_testnet_base("https://testnet.binance.vision/") == (
        "https://testnet.binance.vision"
    )


def test_limit_smoke_order_is_below_market_and_respects_filters():
    params = build_non_filling_limit_buy(
        symbol="SOLUSDT",
        market_price="100.00",
        rules={
            "tick": Decimal("0.01"),
            "step": Decimal("0.001"),
            "min_qty": Decimal("0.001"),
            "min_notional": Decimal("5"),
        },
        notional_usdt="10",
    )
    assert Decimal(params["price"]) == Decimal("50.00")
    assert Decimal(params["quantity"]) * Decimal(params["price"]) >= Decimal("10")
    assert params["newClientOrderId"].startswith("LDBSMO-")
