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


def test_classify_oco_legs_accepts_one_terminal_partial_stop():
    stop = {
        "orderId": 21,
        "side": "SELL",
        "type": "STOP_LOSS_LIMIT",
        "status": "EXPIRED_IN_MATCH",
        "executedQty": "0.040",
    }
    tp = {
        "orderId": 22,
        "side": "SELL",
        "type": "LIMIT_MAKER",
        "status": "CANCELED",
        "executedQty": "0",
    }

    assert classify_oco_legs([stop, tp]) == ("CLOSED", stop, "STOP")


def test_classify_oco_legs_rejects_two_executed_terminal_legs():
    legs = [
        {
            "orderId": 21,
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "status": "EXPIRED",
            "executedQty": "0.040",
        },
        {
            "orderId": 22,
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "status": "CANCELED",
            "executedQty": "0.010",
        },
    ]

    with pytest.raises(RuntimeError, match="ambiguous"):
        classify_oco_legs(legs)


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


def test_recovery_preserves_live_oco_when_verification_read_times_out(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    _protected_oco(journal)
    dependencies = RecoveryDependencies(
        journal=lambda: journal,
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: {
            "orderListId": 20,
            "listStatusType": "EXEC_STARTED",
        },
        verify_oco_legs=lambda symbol, payload: (_ for _ in ()).throw(
            requests.Timeout("read timed out")
        ),
        cancel_oco=lambda symbol, order_list_id: pytest.fail(
            "read uncertainty must preserve live protection"
        ),
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )

    with pytest.raises(RuntimeError, match="left unchanged"):
        recover_existing_protection("BUY-OLD", dependencies=dependencies)
    assert journal.get("OCO-OLD").state == "PROTECTED"
    assert journal.get("BUY-OLD").state == "PROTECTED"


def test_recovery_records_terminal_partial_exit_and_only_residual_inventory(
    tmp_path,
):
    path = tmp_path / "orders.sqlite3"
    journal = OrderJournal(path, venue="mainnet")
    _protected_oco(journal)
    stop = {
        "orderId": 21,
        "clientOrderId": "STOP-OLD",
        "side": "SELL",
        "type": "STOP_LOSS_LIMIT",
        "status": "EXPIRED_IN_MATCH",
        "executedQty": "0.040",
    }
    legs = [
        stop,
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
            "terminal list must not be cancelled"
        ),
        halt=lambda reason, **metadata: None,
        logger=lambda message: None,
    )

    assert recover_existing_protection("BUY-OLD", dependencies=dependencies) is False
    assert recover_existing_protection("BUY-OLD", dependencies=dependencies) is False
    assert journal.get("OCO-OLD").state == "FAILED"
    assert journal.get("BUY-OLD").state == "PROTECTION_PENDING"
    assert journal.partial_protection_exit_quantity("BUY-OLD") == Decimal("0.040")
    managed = read_order_journal_telemetry(path)["managed_buys"]
    assert managed == [
        {"symbol": "SOLUSDT", "quantity": "0.084", "protected_buys": 0}
    ]


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


def test_legacy_json_evidence_is_backfilled_once_into_current_schema(tmp_path):
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
    assert version == ("3",)
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
