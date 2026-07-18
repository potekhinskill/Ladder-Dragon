from ladder_dragon.execution.order_recovery import OrderJournal


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
