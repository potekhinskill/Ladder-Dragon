import sqlite3
from decimal import Decimal

import pytest
import requests

from ladder_dragon.execution.order_recovery import (
    OrderJournal,
    read_order_journal_telemetry,
)
from ladder_dragon.execution.executor_recovery import (
    RecoveryDependencies,
    cancel_order,
    classify_oco_legs,
    get_order,
    list_open_orders,
    reconcile_nonterminal_orders,
    recover_existing_protection,
)

from tests.test_order_recovery import recovery_dependencies

def test_otoco_recovery_requires_filled_working_buy_and_two_active_legs(
    tmp_path,
):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    journal.prepare(
        client_order_id="BUY-OTOCO",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="OTOCO_WORKING",
        quantity="0.1",
        price="100",
    )
    journal.record_exchange_order(
        "BUY-OTOCO",
        {
            "orderId": 10,
            "status": "FILLED",
            "executedQty": "0.1",
            "cummulativeQuoteQty": "10",
        },
    )
    journal.prepare(
        client_order_id="LIST-OTOCO",
        symbol="SOLUSDT",
        side="SELL",
        purpose="otoco",
        order_type="OTOCO",
        quantity="0.1",
        price="105",
        parent_client_order_id="BUY-OTOCO",
    )
    orders = {
        "BUY-OTOCO": {
            "orderId": 10,
            "clientOrderId": "BUY-OTOCO",
            "side": "BUY",
            "type": "LIMIT",
            "status": "FILLED",
        },
        "TP-OTOCO": {
            "orderId": 11,
            "clientOrderId": "TP-OTOCO",
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "status": "NEW",
        },
        "SL-OTOCO": {
            "orderId": 12,
            "clientOrderId": "SL-OTOCO",
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "status": "NEW",
        },
    }
    dependencies = RecoveryDependencies(
        journal=lambda: journal,
        get_order_by_client_id=lambda symbol, client_id: orders.get(client_id),
        get_order_list_by_client_id=lambda client_id: {
            "orderListId": 99,
            "listStatusType": "EXEC_STARTED",
            "orders": [
                {"clientOrderId": "BUY-OTOCO"},
                {"clientOrderId": "TP-OTOCO"},
                {"clientOrderId": "SL-OTOCO"},
            ],
        },
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: pytest.fail(
            "valid OTOCO must not be cancelled"
        ),
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )

    assert recover_existing_protection(
        "BUY-OTOCO",
        dependencies=dependencies,
    ) is True
    assert journal.get("BUY-OTOCO").state == "PROTECTED"
    assert journal.protection_for_leg_order_id(12)[1] == "STOP_LOSS_LIMIT"
    assert journal.created_at_ms_for_exchange_order(12) is not None
    assert journal.unresolved_buys("SOLUSDT") == []
    assert [
        item.client_order_id for item in journal.protected_buys("SOLUSDT")
    ] == ["BUY-OTOCO"]


def test_otoco_read_timeout_preserves_exchange_list(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(
        client_order_id="BUY-OTOCO-TIMEOUT",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="OTOCO_WORKING",
        quantity="0.1",
        price="100",
    )
    journal.record_exchange_order(
        "BUY-OTOCO-TIMEOUT",
        {"orderId": 30, "status": "FILLED", "executedQty": "0.1"},
    )
    journal.prepare(
        client_order_id="LIST-OTOCO-TIMEOUT",
        symbol="SOLUSDT",
        side="SELL",
        purpose="otoco",
        order_type="OTOCO",
        quantity="0.1",
        price="105",
        parent_client_order_id="BUY-OTOCO-TIMEOUT",
    )
    journal.record_order_list(
        "LIST-OTOCO-TIMEOUT",
        {"orderListId": 31, "listStatusType": "EXEC_STARTED"},
    )
    journal.mark_protected(
        parent_client_order_id="BUY-OTOCO-TIMEOUT",
        protection_client_order_id="LIST-OTOCO-TIMEOUT",
        order_list_id=31,
    )
    dependencies = RecoveryDependencies(
        journal=lambda: journal,
        get_order_by_client_id=lambda symbol, client_id: (_ for _ in ()).throw(
            requests.Timeout("read timed out")
        ),
        get_order_list_by_client_id=lambda client_id: {
            "orderListId": 31,
            "listStatusType": "EXEC_STARTED",
            "orders": [
                {"clientOrderId": "BUY-OTOCO-TIMEOUT"},
                {"clientOrderId": "TP-OTOCO-TIMEOUT"},
                {"clientOrderId": "SL-OTOCO-TIMEOUT"},
            ],
        },
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: pytest.fail(
            "read uncertainty must preserve OTOCO"
        ),
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )

    with pytest.raises(RuntimeError, match="left unchanged"):
        recover_existing_protection(
            "BUY-OTOCO-TIMEOUT",
            dependencies=dependencies,
        )
    assert journal.get("LIST-OTOCO-TIMEOUT").state == "PROTECTED"
    assert journal.get("BUY-OTOCO-TIMEOUT").state == "PROTECTED"


def test_cancelled_partial_otoco_must_be_all_done_before_separate_protection(
    tmp_path,
):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    journal.prepare(
        client_order_id="BUY-PARTIAL",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="OTOCO_WORKING",
        quantity="0.1",
        price="100",
    )
    journal.record_exchange_order(
        "BUY-PARTIAL",
        {
            "orderId": 20,
            "status": "CANCELED",
            "executedQty": "0.04",
            "cummulativeQuoteQty": "4",
        },
    )
    journal.prepare(
        client_order_id="LIST-PARTIAL",
        symbol="SOLUSDT",
        side="SELL",
        purpose="otoco",
        order_type="OTOCO",
        quantity="0.1",
        price="105",
        parent_client_order_id="BUY-PARTIAL",
    )
    orders = {
        "BUY-PARTIAL": {
            "clientOrderId": "BUY-PARTIAL",
            "status": "CANCELED",
            "executedQty": "0.04",
        },
        "TP-PARTIAL": {
            "orderId": 21,
            "clientOrderId": "TP-PARTIAL",
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "status": "CANCELED",
        },
        "SL-PARTIAL": {
            "orderId": 22,
            "clientOrderId": "SL-PARTIAL",
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "status": "CANCELED",
        },
    }
    dependencies = RecoveryDependencies(
        journal=lambda: journal,
        get_order_by_client_id=lambda symbol, client_id: orders.get(client_id),
        get_order_list_by_client_id=lambda client_id: {
            "orderListId": 100,
            "listStatusType": "ALL_DONE",
            "orders": [
                {"clientOrderId": "BUY-PARTIAL"},
                {"clientOrderId": "TP-PARTIAL"},
                {"clientOrderId": "SL-PARTIAL"},
            ],
        },
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: pytest.fail(
            "confirmed ALL_DONE list must not be cancelled again"
        ),
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )

    assert recover_existing_protection(
        "BUY-PARTIAL",
        dependencies=dependencies,
    ) is False
    assert journal.get("LIST-PARTIAL").state == "FILLED"


def test_unknown_submission_is_kept_for_reconciliation(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    intent = journal.prepare(
        client_order_id="LDBLAD-unknown",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    journal.mark_unknown(intent.client_order_id, "connection reset after POST")
    unresolved = journal.unresolved_buys("SOLUSDT")
    assert len(unresolved) == 1
    assert unresolved[0].state == "UNKNOWN"
    assert "connection reset" in unresolved[0].last_error


def test_journal_scrubs_signed_urls_from_new_and_historical_errors(tmp_path):
    path = tmp_path / "orders.sqlite3"
    journal = OrderJournal(path)
    intent = journal.prepare(
        client_order_id="LDSLAD-sensitive",
        symbol="SOLUSDT",
        side="SELL",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    signed_error = (
        "400 Client Error for url: "
        "https://api.binance.com/api/v3/order?symbol=SOLUSDT"
        "&timestamp=123&signature=secret-signature"
    )
    updated = journal.mark_unknown(intent.client_order_id, signed_error)
    assert "signature=secret-signature" not in updated.last_error
    assert "?<redacted>" in updated.last_error

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE order_intents SET last_error = ? WHERE client_order_id = ?",
            (signed_error, intent.client_order_id),
        )

    reopened = OrderJournal(path)
    historical = reopened.get(intent.client_order_id)
    assert historical is not None
    assert "signature=secret-signature" not in historical.last_error
    assert "?<redacted>" in historical.last_error


def test_canceled_partial_buy_still_requires_protection(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    intent = journal.prepare(
        client_order_id="LDBLAD-canceled-partial",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    updated = journal.record_exchange_order(
        intent.client_order_id,
        {
            "orderId": 999,
            "status": "CANCELED",
            "executedQty": "0.040",
            "cummulativeQuoteQty": "4.0",
        },
    )
    assert updated.state == "PROTECTION_PENDING"
    assert journal.unresolved_buys("SOLUSDT") == [updated]


def test_filled_regular_sell_does_not_block_a_future_sell(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    intent = journal.prepare(
        client_order_id="LDSLAD-sell",
        symbol="SOLUSDT",
        side="SELL",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="110.00",
    )
    journal.record_exchange_order(
        intent.client_order_id,
        {"orderId": 1000, "status": "FILLED", "executedQty": "0.100"},
    )
    assert journal.find_active(
        symbol="SOLUSDT",
        side="SELL",
        purpose="ladder",
        quantity="0.100",
        price="110.00",
    ) is None


def test_startup_reconciliation_records_external_cancellation(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    intent = journal.prepare(
        client_order_id="LDBLAD-external-cancel",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.126",
        price="75.80",
    )
    journal.record_exchange_order(
        intent.client_order_id,
        {"orderId": 123, "status": "NEW", "executedQty": "0"},
    )
    dependencies = recovery_dependencies(
        journal,
        lambda symbol, client_id: {
            "orderId": 123,
            "clientOrderId": client_id,
            "status": "CANCELED",
            "executedQty": "0.00000000",
        },
    )

    reconciled = reconcile_nonterminal_orders(
        "SOLUSDT", dependencies=dependencies
    )

    assert [item.state for item in reconciled] == ["CANCELED"]
    assert journal.nonterminal_orders("SOLUSDT") == []


def test_startup_reconciliation_closes_confirmed_absent_unknown_sell(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    intent = journal.prepare(
        client_order_id="LDSLAD-confirmed-absent",
        symbol="SOLUSDT",
        side="SELL",
        purpose="ladder",
        order_type="LIMIT",
        quantity="3.755",
        price="230",
    )
    journal.mark_unknown(intent.client_order_id, "definitive response lost")
    logs = []
    dependencies = recovery_dependencies(
        journal, lambda symbol, client_id: None, logs=logs
    )

    reconciled = reconcile_nonterminal_orders(
        "SOLUSDT", dependencies=dependencies
    )

    assert [item.state for item in reconciled] == ["FAILED"]
    assert "exchange confirmed order absent" in reconciled[0].last_error
    assert any("absent; state=FAILED" in line for line in logs)


def test_startup_reconciliation_halts_if_submitted_order_disappears(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    intent = journal.prepare(
        client_order_id="LDBLAD-lost-submitted",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.126",
        price="75.80",
    )
    journal.record_exchange_order(
        intent.client_order_id,
        {"orderId": 123, "status": "NEW", "executedQty": "0"},
    )
    halts = []
    dependencies = recovery_dependencies(
        journal, lambda symbol, client_id: None, halts=halts
    )

    with pytest.raises(RuntimeError, match="exchange lost BUY"):
        reconcile_nonterminal_orders("SOLUSDT", dependencies=dependencies)

    assert len(halts) == 1
