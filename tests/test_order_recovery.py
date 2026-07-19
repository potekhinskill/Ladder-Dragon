import sqlite3

import pytest

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.executor_recovery import (
    RecoveryDependencies,
    reconcile_nonterminal_orders,
)


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
