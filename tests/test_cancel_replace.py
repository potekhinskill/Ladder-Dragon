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


def test_cancel_replace_timeout_retries_before_exchange_state_arrives(tmp_path):
    journal = journal_with_original(tmp_path)
    replacement_id = {"value": ""}
    attempts = {"value": 0}
    sleeps = []
    halts = []

    def signed_request(method, path, params):
        replacement_id["value"] = params["newClientOrderId"]
        raise requests.Timeout("signed-private-value")

    def get_old(symbol, order_id):
        attempts["value"] += 1
        if attempts["value"] < 3:
            return original_order()
        return {**original_order(), "status": "CANCELED"}

    def get_new(symbol, client_id):
        if attempts["value"] < 3:
            return None
        return {
            "orderId": 11,
            "clientOrderId": client_id,
            "status": "NEW",
            "executedQty": "0",
        }

    result = atomic_cancel_replace_buy(
        "SOLUSDT",
        original_order(),
        Decimal("91"),
        maximum_notional=Decimal("10"),
        dependencies=CancelReplaceDependencies(
            journal=lambda: journal,
            signed_request=signed_request,
            get_order_by_id=get_old,
            get_order_by_client_id=get_new,
            halt=lambda reason, **metadata: halts.append((reason, metadata)),
            logger=lambda message: None,
            sleep=sleeps.append,
        ),
    )

    assert result["orderId"] == 11
    assert attempts["value"] == 3
    assert sleeps == [0.25, 0.25]
    assert halts == []
    assert journal.get(replacement_id["value"]).state == "SUBMITTED"


def test_cancel_replace_retries_transient_reconciliation_query(tmp_path):
    journal = journal_with_original(tmp_path)
    replacement_id = {"value": ""}
    attempts = {"value": 0}

    def signed_request(method, path, params):
        replacement_id["value"] = params["newClientOrderId"]
        raise requests.Timeout("unknown ack")

    def get_old(symbol, order_id):
        attempts["value"] += 1
        if attempts["value"] == 1:
            raise requests.Timeout("private-query-value")
        return {**original_order(), "status": "CANCELED"}

    result = atomic_cancel_replace_buy(
        "SOLUSDT",
        original_order(),
        Decimal("91"),
        maximum_notional=Decimal("10"),
        dependencies=CancelReplaceDependencies(
            journal=lambda: journal,
            signed_request=signed_request,
            get_order_by_id=get_old,
            get_order_by_client_id=lambda symbol, client_id: {
                "orderId": 11,
                "clientOrderId": client_id,
                "status": "NEW",
                "executedQty": "0",
            },
            halt=lambda reason, **metadata: pytest.fail(
                "transient query must reconcile"
            ),
            logger=lambda message: None,
            sleep=lambda delay: None,
        ),
    )

    assert attempts["value"] == 2
    assert result["orderId"] == 11
    assert journal.get(replacement_id["value"]).state == "SUBMITTED"


def test_cancel_replace_timeout_never_marks_snapshot_absence_failed(tmp_path):
    journal = journal_with_original(tmp_path)
    replacement_id = {"value": ""}
    halts = []

    def signed_request(method, path, params):
        replacement_id["value"] = params["newClientOrderId"]
        raise requests.Timeout("signed-private-value")

    with pytest.raises(RuntimeError, match="ambiguous"):
        atomic_cancel_replace_buy(
            "SOLUSDT",
            original_order(),
            Decimal("91"),
            maximum_notional=Decimal("10"),
            dependencies=CancelReplaceDependencies(
                journal=lambda: journal,
                signed_request=signed_request,
                get_order_by_id=lambda symbol, order_id: original_order(),
                get_order_by_client_id=lambda symbol, client_id: None,
                halt=lambda reason, **metadata: halts.append(
                    (reason, metadata)
                ),
                logger=lambda message: None,
                sleep=lambda delay: None,
            ),
        )

    intent = journal.get(replacement_id["value"])
    assert intent.state == "UNKNOWN"
    assert "private-value" not in (intent.last_error or "")
    assert len(halts) == 1


def test_cancel_replace_structured_noop_does_not_halt(tmp_path):
    journal = journal_with_original(tmp_path)
    replacement_id = {"value": ""}
    halts = []

    def signed_request(method, path, params):
        replacement_id["value"] = params["newClientOrderId"]
        return {
            "cancelResult": "FAILURE",
            "newOrderResult": "NOT_ATTEMPTED",
            "cancelResponse": {
                "code": -2011,
                "msg": "Order was not canceled due to cancel restrictions.",
            },
            "newOrderResponse": None,
        }

    result = atomic_cancel_replace_buy(
        "SOLUSDT",
        original_order(),
        Decimal("91"),
        maximum_notional=Decimal("10"),
        dependencies=CancelReplaceDependencies(
            journal=lambda: journal,
            signed_request=signed_request,
            get_order_by_id=lambda symbol, order_id: pytest.fail(
                "structured no-op must not be reconciled"
            ),
            get_order_by_client_id=lambda symbol, client_id: pytest.fail(
                "structured no-op must not be reconciled"
            ),
            halt=lambda reason, **metadata: halts.append((reason, metadata)),
            logger=lambda message: None,
        ),
    )

    assert result is None
    assert halts == []
    assert journal.get(replacement_id["value"]).state == "FAILED"
    assert journal.get("OLD-BUY").state == "SUBMITTED"


def test_cancel_replace_reconciliation_accepts_filled_replacement(tmp_path):
    journal = journal_with_original(tmp_path)
    replacement_id = {"value": ""}
    halts = []

    def signed_request(method, path, params):
        replacement_id["value"] = params["newClientOrderId"]
        raise requests.Timeout("unknown ack")

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
                "status": "FILLED",
                "executedQty": "0.1",
                "cummulativeQuoteQty": "9.1",
            },
            halt=lambda reason, **metadata: halts.append((reason, metadata)),
            logger=lambda message: None,
            sleep=lambda delay: None,
        ),
    )

    assert result["status"] == "FILLED"
    assert journal.get(replacement_id["value"]).state == "FILLED"
    assert journal.get("OLD-BUY").state == "CANCELED"
    assert halts == []


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
