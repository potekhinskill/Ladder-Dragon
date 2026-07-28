import sqlite3

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


def test_classify_oco_legs_never_treats_canceled_pair_as_active():
    legs = [
        {
            "orderId": 21,
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "status": "CANCELED",
            "executedQty": "0.00000000",
        },
        {
            "orderId": 22,
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "status": "CANCELED",
            "executedQty": "0.00000000",
        },
    ]

    assert classify_oco_legs(legs) == ("CANCELED", None, None)


def test_classify_oco_legs_identifies_exact_terminal_sell():
    stop = {
        "orderId": 21,
        "side": "SELL",
        "type": "STOP_LOSS_LIMIT",
        "status": "FILLED",
        "executedQty": "0.124",
    }
    tp = {
        "orderId": 22,
        "side": "SELL",
        "type": "LIMIT_MAKER",
        "status": "CANCELED",
        "executedQty": "0",
    }

    assert classify_oco_legs([stop, tp]) == ("CLOSED", stop, "STOP")


def _protected_oco(journal: OrderJournal) -> None:
    journal.prepare(
        client_order_id="BUY-OLD",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.124",
        price="77.33",
    )
    journal.record_exchange_order(
        "BUY-OLD",
        {"orderId": 10, "status": "FILLED", "executedQty": "0.124"},
    )
    journal.prepare(
        client_order_id="OCO-OLD",
        symbol="SOLUSDT",
        side="SELL",
        purpose="oco:BUY-OLD",
        order_type="OCO",
        quantity="0.124",
        price="78",
        parent_client_order_id="BUY-OLD",
    )
    journal.record_order_list(
        "OCO-OLD",
        {"orderListId": 20, "listStatusType": "EXEC_STARTED"},
    )
    journal.mark_protected(
        parent_client_order_id="BUY-OLD",
        protection_client_order_id="OCO-OLD",
        order_list_id=20,
    )


def test_recovery_demotes_all_done_oco_without_sell_fill(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    _protected_oco(journal)
    legs = [
        {
            "orderId": 21,
            "clientOrderId": "STOP-OLD",
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "status": "CANCELED",
            "executedQty": "0",
        },
        {
            "orderId": 22,
            "clientOrderId": "TP-OLD",
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "status": "CANCELED",
            "executedQty": "0",
        },
    ]
    dependencies = RecoveryDependencies(
        journal=lambda: journal,
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: {
            "orderListId": 20,
            "listStatusType": "ALL_DONE",
        },
        verify_oco_legs=lambda symbol, payload: legs,
        cancel_oco=lambda symbol, order_list_id: pytest.fail(
            "terminal OCO must not be cancelled again"
        ),
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )

    assert recover_existing_protection(
        "BUY-OLD",
        dependencies=dependencies,
    ) is False
    assert journal.get("OCO-OLD").state == "FAILED"
    assert journal.get("BUY-OLD").state == "PROTECTION_PENDING"


def test_recovery_closes_all_done_oco_with_exact_sell_fill(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    _protected_oco(journal)
    tp = {
        "orderId": 22,
        "clientOrderId": "TP-OLD",
        "side": "SELL",
        "type": "LIMIT_MAKER",
        "status": "FILLED",
        "executedQty": "0.124",
    }
    legs = [
        {
            "orderId": 21,
            "clientOrderId": "STOP-OLD",
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "status": "CANCELED",
            "executedQty": "0",
        },
        tp,
    ]
    dependencies = RecoveryDependencies(
        journal=lambda: journal,
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: {
            "orderListId": 20,
            "listStatusType": "ALL_DONE",
        },
        verify_oco_legs=lambda symbol, payload: legs,
        cancel_oco=lambda symbol, order_list_id: pytest.fail(
            "closed OCO must not be cancelled again"
        ),
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )

    assert recover_existing_protection(
        "BUY-OLD",
        dependencies=dependencies,
    ) is True
    assert journal.get("OCO-OLD").state == "CLOSED"
    assert journal.get("BUY-OLD").state == "CLOSED"
    assert journal.get("OCO-OLD").metadata["exit_reason"] == "TP"


def recovery_dependencies(journal, lookup, *, halts=None, logs=None):
    return RecoveryDependencies(
        journal=lambda: journal,
        get_order_by_client_id=lookup,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: (halts if halts is not None else []).append(
            (reason, metadata)
        ),
        logger=(logs if logs is not None else []).append,
    )


def test_exchange_read_and_cancel_wrappers_fail_closed():
    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("network unavailable")

    with pytest.raises(requests.ConnectionError):
        list_open_orders("SOLUSDT", signed_request=unavailable, logger=lambda _: None)
    with pytest.raises(requests.ConnectionError):
        get_order(
            "SOLUSDT",
            123,
            signed_request=unavailable,
            record_payload=lambda payload: None,
            logger=lambda _: None,
        )
    with pytest.raises(requests.ConnectionError):
        cancel_order(
            "SOLUSDT", 123, signed_request=unavailable, logger=lambda _: None
        )


def test_open_orders_rejects_invalid_success_payload():
    with pytest.raises(RuntimeError, match="not a list"):
        list_open_orders(
            "SOLUSDT",
            signed_request=lambda *args, **kwargs: {"status": "ok"},
            logger=lambda _: None,
        )


def test_journal_reuses_active_intent_and_records_exchange_state(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    created = journal.prepare(
        client_order_id="LDBLAD-test",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    assert created.state == "PREPARED"

    active = journal.find_active(
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        quantity="0.100",
        price="100.00",
    )
    assert active is not None
    assert active.client_order_id == created.client_order_id

    submitted = journal.record_exchange_order(
        created.client_order_id,
        {"orderId": 123, "status": "NEW", "executedQty": "0"},
    )
    assert submitted.state == "SUBMITTED"
    assert submitted.exchange_order_id == 123

    partial = journal.record_exchange_order(
        created.client_order_id,
        {
            "orderId": 123,
            "status": "PARTIALLY_FILLED",
            "executedQty": "0.040",
            "cummulativeQuoteQty": "4.0",
        },
    )
    assert partial.state == "PARTIALLY_FILLED"
    assert partial.executed_qty == "0.040"


def test_prepare_is_decimal_idempotent_and_rejects_safe_conflicts(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    first = journal.prepare(
        client_order_id="SAME-ID",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1000",
        price="100.00",
        metadata={"private": "do-not-print"},
    )
    repeated = journal.prepare(
        client_order_id="SAME-ID",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="1E2",
        metadata={"private": "do-not-print"},
    )
    assert repeated == first
    assert repeated.quantity == "0.1000"

    with pytest.raises(ValueError) as caught:
        journal.prepare(
            client_order_id="SAME-ID",
            symbol="ETHUSDT",
            side="BUY",
            purpose="ladder",
            order_type="LIMIT",
            quantity="0.2",
            price="100",
            metadata={"private": "different-secret"},
        )
    message = str(caught.value)
    assert "symbol" in message and "quantity" in message and "metadata" in message
    assert "do-not-print" not in message
    assert "different-secret" not in message


def test_find_active_compares_historical_decimal_text_numerically(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    journal.prepare(
        client_order_id="NUMERIC-ID",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="100",
    )
    with sqlite3.connect(journal.path) as con:
        con.execute(
            "UPDATE order_intents SET quantity = '0.100000', price = '1E+2' "
            "WHERE client_order_id = 'NUMERIC-ID'"
        )

    active = journal.find_active(
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        quantity="0.1",
        price="100.00",
    )
    assert active is not None
    assert active.client_order_id == "NUMERIC-ID"


def test_runtime_telemetry_contains_only_sanitized_journal_summary(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    cancelled = journal.prepare(
        client_order_id="LDBLAD-secret-cancelled",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="90",
        metadata={"private": "must-not-leak"},
    )
    journal.record_exchange_order(
        cancelled.client_order_id,
        {"orderId": 101, "status": "CANCELED", "executedQty": "0"},
    )
    journal.prepare(
        client_order_id="LDBLAD-secret-pending",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.2",
        price="80",
    )

    telemetry = read_order_journal_telemetry(journal.path)

    assert telemetry["available"] is True
    assert telemetry["counts"] == {"CANCELED": 1, "PREPARED": 1}
    assert telemetry["cancelled"] == 1
    assert telemetry["pending"] == 1
    assert telemetry["latest"]["symbol"] == "SOLUSDT"
    serialized = str(telemetry)
    assert "LDBLAD-secret" not in serialized
    assert "must-not-leak" not in serialized


def test_exact_oco_leg_closure_is_the_only_promotion_evidence(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(
        client_order_id="BUY-1", symbol="SOLUSDT", side="BUY",
        purpose="ladder", order_type="LIMIT", quantity="0.1", price="100",
    )
    journal.record_exchange_order(
        "BUY-1", {"orderId": 10, "status": "FILLED", "executedQty": "0.1"}
    )
    journal.prepare(
        client_order_id="OCO-1", symbol="SOLUSDT", side="SELL",
        purpose="oco", order_type="OCO", quantity="0.1", price="102",
        parent_client_order_id="BUY-1",
    )
    journal.record_order_list(
        "OCO-1", {"orderListId": 20, "listStatusType": "EXEC_STARTED"}
    )
    journal.record_verified_protection_legs(
        "OCO-1",
        [
            {"orderId": 21, "clientOrderId": "TP-1", "type": "LIMIT_MAKER"},
            {"orderId": 22, "clientOrderId": "SL-1", "type": "STOP_LOSS_LIMIT"},
        ],
    )
    journal.mark_protected(
        parent_client_order_id="BUY-1", protection_client_order_id="OCO-1",
        order_list_id=20,
    )

    match = journal.protection_for_leg_order_id(22)
    assert match is not None and match[1] == "STOP_LOSS_LIMIT"
    assert read_order_journal_telemetry(journal.path)["lifecycle"]["closed_exact"] == 0

    journal.mark_exact_lifecycle_closed(
        protection_client_order_id="OCO-1", exit_order_id=22,
        exit_reason="STOP",
    )
    assert read_order_journal_telemetry(journal.path)["lifecycle"] == {
        "closed_exact": 1, "tp": 0, "stop": 1, "required": 3,
        "promotion_ready": False,
    }


def _prepared_verified_lifecycle(journal: OrderJournal) -> None:
    journal.prepare(
        client_order_id="BUY-ATOMIC",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="100",
    )
    journal.record_exchange_order(
        "BUY-ATOMIC",
        {"orderId": 110, "status": "FILLED", "executedQty": "0.1"},
    )
    journal.prepare(
        client_order_id="OCO-ATOMIC",
        symbol="SOLUSDT",
        side="SELL",
        purpose="oco",
        order_type="OCO",
        quantity="0.1",
        price="102",
        parent_client_order_id="BUY-ATOMIC",
    )
    journal.record_order_list(
        "OCO-ATOMIC",
        {"orderListId": 120, "listStatusType": "EXEC_STARTED"},
    )


def test_verified_protection_rolls_back_as_one_transition(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    _prepared_verified_lifecycle(journal)
    with sqlite3.connect(journal.path) as con:
        con.execute(
            """
            CREATE TRIGGER fail_parent_protection
            BEFORE UPDATE OF state ON order_intents
            WHEN OLD.client_order_id = 'BUY-ATOMIC'
                 AND NEW.state = 'PROTECTED'
            BEGIN
                SELECT RAISE(ABORT, 'injected parent failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        journal.mark_verified_protected(
            parent_client_order_id="BUY-ATOMIC",
            protection_client_order_id="OCO-ATOMIC",
            legs=[
                {"orderId": 121, "clientOrderId": "TP-A", "type": "LIMIT_MAKER"},
                {
                    "orderId": 122,
                    "clientOrderId": "SL-A",
                    "type": "STOP_LOSS_LIMIT",
                },
            ],
            order_list_id=120,
        )

    assert journal.get("BUY-ATOMIC").state == "FILLED"
    assert journal.get("OCO-ATOMIC").state == "SUBMITTED"
    assert journal.protection_for_leg_order_id(121, symbol="SOLUSDT") is None
    assert "verified_legs" not in journal.get("OCO-ATOMIC").metadata


def test_exact_closure_rolls_back_metadata_states_and_evidence(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    _prepared_verified_lifecycle(journal)
    journal.mark_verified_protected(
        parent_client_order_id="BUY-ATOMIC",
        protection_client_order_id="OCO-ATOMIC",
        legs=[
            {"orderId": 121, "clientOrderId": "TP-A", "type": "LIMIT_MAKER"},
            {
                "orderId": 122,
                "clientOrderId": "SL-A",
                "type": "STOP_LOSS_LIMIT",
            },
        ],
        order_list_id=120,
    )
    with sqlite3.connect(journal.path) as con:
        con.execute(
            """
            CREATE TRIGGER fail_parent_closure
            BEFORE UPDATE OF state ON order_intents
            WHEN OLD.client_order_id = 'BUY-ATOMIC'
                 AND NEW.state = 'CLOSED'
            BEGIN
                SELECT RAISE(ABORT, 'injected parent failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        journal.mark_exact_lifecycle_closed(
            protection_client_order_id="OCO-ATOMIC",
            exit_order_id=121,
            exit_reason="TP",
        )

    assert journal.get("BUY-ATOMIC").state == "PROTECTED"
    assert journal.get("OCO-ATOMIC").state == "PROTECTED"
    assert "exact_lifecycle" not in journal.get("BUY-ATOMIC").metadata
    assert "exact_lifecycle" not in journal.get("OCO-ATOMIC").metadata
    assert read_order_journal_telemetry(journal.path)["lifecycle"]["closed_exact"] == 0


def test_normalized_evidence_does_not_depend_on_metadata_scans(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    _prepared_verified_lifecycle(journal)
    journal.mark_verified_protected(
        parent_client_order_id="BUY-ATOMIC",
        protection_client_order_id="OCO-ATOMIC",
        legs=[
            {"orderId": 121, "clientOrderId": "TP-A", "type": "LIMIT_MAKER"},
            {
                "orderId": 122,
                "clientOrderId": "SL-A",
                "type": "STOP_LOSS_LIMIT",
            },
        ],
        order_list_id=120,
    )
    journal.mark_exact_lifecycle_closed(
        protection_client_order_id="OCO-ATOMIC",
        exit_order_id=121,
        exit_reason="TP",
    )
    with sqlite3.connect(journal.path) as con:
        con.execute(
            "UPDATE order_intents SET metadata_json = '{broken' "
            "WHERE client_order_id IN ('BUY-ATOMIC', 'OCO-ATOMIC')"
        )

    match = journal.protection_for_leg_order_id(121, symbol="SOLUSDT")
    assert match is not None and match[1] == "LIMIT_MAKER"
    lifecycle = read_order_journal_telemetry(journal.path)["lifecycle"]
    assert lifecycle["closed_exact"] == 1
    assert lifecycle["tp"] == 1


def test_legacy_json_evidence_is_backfilled_once_into_schema_v2(tmp_path):
    path = tmp_path / "orders.sqlite3"
    journal = OrderJournal(path, venue="mainnet")
    _prepared_verified_lifecycle(journal)
    journal.mark_verified_protected(
        parent_client_order_id="BUY-ATOMIC",
        protection_client_order_id="OCO-ATOMIC",
        legs=[
            {"orderId": 121, "clientOrderId": "TP-A", "type": "LIMIT_MAKER"},
            {
                "orderId": 122,
                "clientOrderId": "SL-A",
                "type": "STOP_LOSS_LIMIT",
            },
        ],
        order_list_id=120,
    )
    journal.mark_exact_lifecycle_closed(
        protection_client_order_id="OCO-ATOMIC",
        exit_order_id=121,
        exit_reason="TP",
    )
    journal.close()
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE order_lifecycle_closures")
        con.execute("DROP TABLE order_intent_legs")
        con.execute("DROP TABLE order_journal_meta")

    migrated = OrderJournal(path, venue="mainnet")

    match = migrated.protection_for_leg_order_id(121, symbol="SOLUSDT")
    assert match is not None and match[0].client_order_id == "OCO-ATOMIC"
    assert read_order_journal_telemetry(path)["lifecycle"]["closed_exact"] == 1
    with sqlite3.connect(path) as con:
        version = con.execute(
            "SELECT value FROM order_journal_meta WHERE key = 'schema_version'"
        ).fetchone()
        legs = con.execute("SELECT COUNT(*) FROM order_intent_legs").fetchone()
    assert version == ("2",)
    assert legs == (2,)


def test_journal_telemetry_separates_open_managed_lot(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(
        client_order_id="BUY-1", symbol="SOLUSDT", side="BUY",
        purpose="ladder", order_type="LIMIT", quantity="0.124", price="77.33",
    )
    journal.record_exchange_order(
        "BUY-1", {"orderId": 10, "status": "FILLED", "executedQty": "0.124"}
    )
    journal.prepare(
        client_order_id="OCO-1", symbol="SOLUSDT", side="SELL",
        purpose="oco", order_type="OCO", quantity="0.124", price="78",
        parent_client_order_id="BUY-1",
    )
    journal.record_order_list(
        "OCO-1", {"orderListId": 20, "listStatusType": "EXEC_STARTED"}
    )
    journal.mark_protected(
        parent_client_order_id="BUY-1",
        protection_client_order_id="OCO-1",
        order_list_id=20,
    )

    telemetry = read_order_journal_telemetry(journal.path)

    assert telemetry["managed_buys"] == [{
        "symbol": "SOLUSDT",
        "quantity": "0.124",
        "protected_buys": 1,
    }]


def test_filled_buy_remains_unresolved_until_protection_is_confirmed(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    buy = journal.prepare(
        client_order_id="LDBLAD-buy",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    journal.record_exchange_order(
        buy.client_order_id,
        {
            "orderId": 321,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
    )
    assert [item.client_order_id for item in journal.unresolved_buys("SOLUSDT")] == [
        buy.client_order_id
    ]

    protection = journal.prepare(
        client_order_id="LDSOCO-protection",
        parent_client_order_id=buy.client_order_id,
        symbol="SOLUSDT",
        side="SELL",
        purpose="oco",
        order_type="OCO",
        quantity="0.100",
        price="105.00",
    )
    assert journal.protection_for_parent(buy.client_order_id) == protection
    journal.mark_protected(
        parent_client_order_id=buy.client_order_id,
        protection_client_order_id=protection.client_order_id,
        order_list_id=456,
    )
    assert journal.get(buy.client_order_id).state == "PROTECTED"
    assert journal.get(protection.client_order_id).exchange_order_list_id == 456
    assert journal.unresolved_buys("SOLUSDT") == []
    assert [
        item.client_order_id for item in journal.protected_buys("SOLUSDT")
    ] == [buy.client_order_id]


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
    assert journal.unresolved_buys("SOLUSDT") == []
    assert [
        item.client_order_id for item in journal.protected_buys("SOLUSDT")
    ] == ["BUY-OTOCO"]


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
