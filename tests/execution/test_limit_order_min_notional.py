from decimal import Decimal

import pytest

from ladder_dragon.execution.orders.runtime import (
    OrderDependencies,
    place_limit_order,
)


def _dependencies(calls: list[dict[str, object]]) -> OrderDependencies:
    return OrderDependencies(
        live=lambda: True,
        logger=lambda message: None,
        pull_filters=lambda symbol: {
            "tickSizeExact": "0.01",
            "stepSizeExact": "0.01",
            "minQtyExact": "0.01",
            "minNotionalExact": "5",
        },
        round_price=lambda *args: pytest.fail("legacy price rounding"),
        round_qty=lambda *args: pytest.fail("legacy quantity rounding"),
        min_qty=lambda *args: pytest.fail("legacy minimum quantity"),
        min_notional=lambda *args: pytest.fail("legacy minimum notional"),
        format_price=lambda *args: pytest.fail("legacy price formatting"),
        format_qty=lambda *args: pytest.fail("legacy quantity formatting"),
        journal=lambda: None,
        signed_request=lambda method, path, params: calls.append(params) or {
            "orderId": 41,
            "status": "NEW",
            "executedQty": "0",
        },
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: None,
        validate_limit_sell_prices=lambda symbol, prices: None,
    )


def test_exact_buy_raises_quantity_to_minimum_notional():
    calls: list[dict[str, object]] = []

    result = place_limit_order(
        "BUY",
        "SOLUSDT",
        Decimal("0.049"),
        Decimal("100"),
        dependencies=_dependencies(calls),
        maximum_notional=Decimal("5"),
    )

    assert result is not None
    assert calls[0]["quantity"] == "0.05"
    assert calls[0]["price"] == "100.00"
    assert result["origQty"] == "0.05"


def test_exact_buy_bump_stays_fail_closed_above_approved_cap():
    calls: list[dict[str, object]] = []

    result = place_limit_order(
        "BUY",
        "SOLUSDT",
        Decimal("0.049"),
        Decimal("100"),
        dependencies=_dependencies(calls),
        maximum_notional=Decimal("4.99"),
    )

    assert result is None
    assert calls == []


def test_exact_sell_never_increases_available_quantity():
    calls: list[dict[str, object]] = []

    result = place_limit_order(
        "SELL",
        "SOLUSDT",
        Decimal("0.049"),
        Decimal("100"),
        dependencies=_dependencies(calls),
    )

    assert result is None
    assert calls == []
