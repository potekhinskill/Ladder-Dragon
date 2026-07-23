from decimal import Decimal

import pytest
import requests

from ladder_dragon.execution.cancel_replace import (
    CancelReplaceDependencies,
    atomic_cancel_replace_buy,
)
from ladder_dragon.execution.order_recovery import OrderJournal


def original_order():
    return {
        "symbol": "SOLUSDT",
        "orderId": 10,
        "clientOrderId": "OLD-BUY",
        "side": "BUY",
        "type": "LIMIT_MAKER",
        "status": "NEW",
        "origQty": "0.1",
        "executedQty": "0",
        "price": "90",
    }


def journal_with_original(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    journal.prepare(
        client_order_id="OLD-BUY",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT_MAKER",
        quantity="0.1",
        price="90",
    )
    journal.record_exchange_order("OLD-BUY", original_order())
    return journal


def test_cancel_replace_commits_replacement_before_atomic_request(tmp_path):
    journal = journal_with_original(tmp_path)
    calls = []

    def signed_request(method, path, params):
        assert journal.get(params["newClientOrderId"]).state == "PREPARED"
        calls.append((method, path, params))
        return {
            "cancelResult": "SUCCESS",
            "newOrderResult": "SUCCESS",
            "cancelResponse": {
                **original_order(),
                "status": "CANCELED",
            },
            "newOrderResponse": {
                "orderId": 11,
                "clientOrderId": params["newClientOrderId"],
                "status": "NEW",
                "executedQty": "0",
            },
        }

    result = atomic_cancel_replace_buy(
        "SOLUSDT",
        original_order(),
        Decimal("91"),
        maximum_notional=Decimal("10"),
        dependencies=CancelReplaceDependencies(
            journal=lambda: journal,
            signed_request=signed_request,
            get_order_by_id=lambda symbol, order_id: None,
            get_order_by_client_id=lambda symbol, client_id: None,
            halt=lambda reason, **metadata: None,
            logger=lambda message: None,
        ),
    )

    assert result["orderId"] == 11
    assert calls[0][1] == "/api/v3/order/cancelReplace"
    assert calls[0][2]["cancelReplaceMode"] == "STOP_ON_FAILURE"
    assert calls[0][2]["cancelRestrictions"] == "ONLY_NEW"
    assert journal.get("OLD-BUY").state == "CANCELED"


def test_cancel_replace_unknown_ack_reconciles_without_resubmit(tmp_path):
    journal = journal_with_original(tmp_path)
    calls = []
    replacement_id = {"value": ""}

    def signed_request(method, path, params):
        calls.append((method, path, params))
        replacement_id["value"] = params["newClientOrderId"]
        raise requests.Timeout("private-value")

    result = atomic_cancel_replace_buy(
        "SOLUSDT",
        original_order(),
        Decimal("91"),
        maximum_notional=Decimal("10"),
        dependencies=CancelReplaceDependencies(
            journal=lambda: journal,
            signed_request=signed_request,
            get_order_by_id=lambda symbol, order_id: {
                **original_order(),
                "status": "CANCELED",
            },
            get_order_by_client_id=lambda symbol, client_id: {
                "orderId": 11,
                "clientOrderId": client_id,
                "status": "NEW",
                "executedQty": "0",
            },
            halt=lambda reason, **metadata: None,
            logger=lambda message: None,
        ),
    )

    assert result["orderId"] == 11
    assert len(calls) == 1
    assert journal.get(replacement_id["value"]).state == "SUBMITTED"


def test_cancel_replace_rejects_partial_fill_and_cap_increase(tmp_path):
    journal = journal_with_original(tmp_path)
    dependencies = CancelReplaceDependencies(
        journal=lambda: journal,
        signed_request=lambda *args: pytest.fail("mutation must be blocked"),
        get_order_by_id=lambda symbol, order_id: None,
        get_order_by_client_id=lambda symbol, client_id: None,
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )
    partial = {**original_order(), "executedQty": "0.01"}

    with pytest.raises(ValueError, match="zero-fill"):
        atomic_cancel_replace_buy(
            "SOLUSDT",
            partial,
            "91",
            maximum_notional="10",
            dependencies=dependencies,
        )
    with pytest.raises(ValueError, match="CAP"):
        atomic_cancel_replace_buy(
            "SOLUSDT",
            original_order(),
            "101",
            maximum_notional="10",
            dependencies=dependencies,
        )
