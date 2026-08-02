# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify OTOCO submission recovery and rejection state.

from decimal import Decimal

import pytest
import requests

from ladder_dragon.execution.binance_transport import BinanceResponseError
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.orders.runtime import OrderDependencies, place_otoco_buy


def _dependencies(journal, *, submit, reconcile, lookup, halts):
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
        signed_request=submit,
        get_order_by_client_id=lookup,
        get_order_list_by_client_id=reconcile,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: halts.append(reason),
        validate_limit_sell_prices=lambda symbol, prices: None,
    )


def _place(dependencies):
    return place_otoco_buy(
        "SOLUSDT",
        Decimal("0.1"),
        Decimal("100"),
        Decimal("105"),
        Decimal("95"),
        Decimal("94.9"),
        dependencies=dependencies,
    )


def test_lost_ack_reconciliation_marks_filled_otoco_as_protected(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    submitted = {}
    halts = []

    def submit(method, path, params):
        submitted.update(params)
        raise requests.Timeout("ACK unavailable")

    def reconciled(_client_id):
        return {
            "orderListId": 701,
            "listStatusType": "EXEC_STARTED",
            "orders": [
                {"clientOrderId": submitted["workingClientOrderId"]},
                {"clientOrderId": submitted["pendingAboveClientOrderId"]},
                {"clientOrderId": submitted["pendingBelowClientOrderId"]},
            ],
        }

    def lookup(_symbol, client_id):
        if client_id == submitted["workingClientOrderId"]:
            return {
                "orderId": 70,
                "clientOrderId": client_id,
                "side": "BUY",
                "type": "LIMIT",
                "status": "FILLED",
                "executedQty": "0.1",
            }
        leg_type = (
            "LIMIT_MAKER"
            if client_id == submitted["pendingAboveClientOrderId"]
            else "STOP_LOSS_LIMIT"
        )
        return {
            "orderId": 71 if leg_type == "LIMIT_MAKER" else 72,
            "clientOrderId": client_id,
            "side": "SELL",
            "type": leg_type,
            "status": "NEW",
        }

    result = _place(
        _dependencies(
            journal,
            submit=submit,
            reconcile=reconciled,
            lookup=lookup,
            halts=halts,
        )
    )

    assert result["orderListId"] == 701
    assert journal.get(submitted["workingClientOrderId"]).state == "PROTECTED"
    protection = journal.get(submitted["listClientOrderId"])
    assert protection.state == "PROTECTED"
    assert len(protection.metadata["verified_legs"]) == 2
    assert halts == []


def test_definitive_otoco_rejection_fails_working_and_list_intents(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    submitted = {}
    response = requests.Response()
    response.status_code = 400

    def reject(_method, _path, params):
        submitted.update(params)
        raise BinanceResponseError(
            status=400,
            code=-1013,
            message="invalid order",
            endpoint="/api/v3/orderList/otoco",
            response=response,
        )

    dependencies = _dependencies(
        journal,
        submit=reject,
        reconcile=lambda client_id: pytest.fail(
            "definitive rejection must not reconcile"
        ),
        lookup=lambda symbol, client_id: pytest.fail(
            "definitive rejection must not query orders"
        ),
        halts=[],
    )
    with pytest.raises(BinanceResponseError):
        _place(dependencies)

    assert journal.get(submitted["workingClientOrderId"]).state == "FAILED"
    assert journal.get(submitted["listClientOrderId"]).state == "FAILED"
