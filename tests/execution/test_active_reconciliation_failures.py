from decimal import Decimal

import pytest
import requests

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.orders.runtime import (
    OrderDependencies,
    place_market_order,
    place_oco_sell,
    place_otoco_buy,
)


def _dependencies(journal: OrderJournal, posts: list[object]) -> OrderDependencies:
    def unavailable(*_args):
        raise requests.ConnectionError("active reconciliation unavailable")

    return OrderDependencies(
        live=lambda: True,
        logger=lambda message: None,
        pull_filters=lambda symbol: {
            "tickSizeExact": "0.01",
            "stepSizeExact": "0.001",
            "minQtyExact": "0.001",
            "minNotionalExact": "5",
        },
        round_price=lambda symbol, value: value,
        round_qty=lambda symbol, value: value,
        min_qty=lambda symbol, hint: Decimal("0.001"),
        min_notional=lambda symbol, price: Decimal("5"),
        format_price=lambda symbol, value: format(value, "f"),
        format_qty=lambda symbol, value: format(value, "f"),
        journal=lambda: journal,
        signed_request=lambda *args: posts.append(args),
        get_order_by_client_id=unavailable,
        get_order_list_by_client_id=unavailable,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: None,
        validate_limit_sell_prices=lambda symbol, prices: None,
    )


def test_market_active_lookup_failure_marks_intent_unknown(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    intent = journal.prepare(
        client_order_id="MARKET-ACTIVE",
        symbol="SOLUSDT",
        side="SELL",
        purpose="market",
        order_type="MARKET",
        quantity="0.100",
        price="MARKET",
    )
    posts: list[object] = []

    with pytest.raises(requests.ConnectionError):
        place_market_order(
            "SOLUSDT",
            "SELL",
            Decimal("0.1"),
            ref_price=Decimal("100"),
            dependencies=_dependencies(journal, posts),
        )

    assert journal.get(intent.client_order_id).state == "UNKNOWN"
    assert posts == []


def test_oco_active_lookup_failure_marks_protection_unknown(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    parent_id = "PARENT-BUY-ACTIVE"
    intent = journal.prepare(
        client_order_id="OCO-ACTIVE",
        symbol="SOLUSDT",
        side="SELL",
        purpose=f"oco:{parent_id[:12]}",
        order_type="OCO",
        quantity="0.100",
        price="110.00",
        parent_client_order_id=parent_id,
    )
    posts: list[object] = []

    with pytest.raises(requests.ConnectionError):
        place_oco_sell(
            "SOLUSDT",
            Decimal("0.1"),
            Decimal("110"),
            Decimal("95"),
            Decimal("94"),
            parent_client_order_id=parent_id,
            dependencies=_dependencies(journal, posts),
        )

    assert journal.get(intent.client_order_id).state == "UNKNOWN"
    assert posts == []


def test_otoco_active_lookup_failure_marks_protection_unknown(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    working = journal.prepare(
        client_order_id="OTOCO-WORKING",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="OTOCO_WORKING",
        quantity="0.100",
        price="100.00",
    )
    protection = journal.prepare(
        client_order_id="OTOCO-LIST",
        symbol="SOLUSDT",
        side="SELL",
        purpose=f"otoco:{working.client_order_id[:12]}",
        order_type="OTOCO",
        quantity="0.100",
        price="105.00",
        parent_client_order_id=working.client_order_id,
    )
    posts: list[object] = []

    with pytest.raises(requests.ConnectionError):
        place_otoco_buy(
            "SOLUSDT",
            Decimal("0.1"),
            Decimal("100"),
            Decimal("105"),
            Decimal("95"),
            Decimal("94.9"),
            dependencies=_dependencies(journal, posts),
        )

    assert journal.get(protection.client_order_id).state == "UNKNOWN"
    assert posts == []
