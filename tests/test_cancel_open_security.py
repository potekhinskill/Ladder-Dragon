import os
import sys

import pytest

from bin import tools_cancel_open
from ladder_dragon.execution.order_recovery import OrderJournal


def parse(monkeypatch, *arguments):
    monkeypatch.setattr(
        sys,
        "argv",
        ["tools_cancel_open.py", "--pairs", "SOLUSDT", *arguments],
    )
    return tools_cancel_open.parse_args()


def test_cancel_tool_defaults_to_testnet_dry(monkeypatch):
    args = parse(monkeypatch)
    assert args.testnet is True
    assert args.live is False
    assert args.base_url == tools_cancel_open.DEFAULT_TEST


def test_cancel_tool_live_requires_confirmation(monkeypatch):
    monkeypatch.delenv("BOT_LIVE_CONFIRMED", raising=False)
    with pytest.raises(SystemExit) as exc:
        parse(monkeypatch, "--live")
    assert exc.value.code == 2


def test_cancel_tool_mainnet_requires_second_confirmation(monkeypatch):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    monkeypatch.delenv("BOT_MAINNET_CANCEL_CONFIRMED", raising=False)
    with pytest.raises(SystemExit) as exc:
        parse(monkeypatch, "--mainnet", "--live")
    assert exc.value.code == 2


def test_cancel_tool_rejects_custom_key_exfiltration_endpoint(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        parse(monkeypatch, "--base-url", "https://attacker.example")
    assert exc.value.code == 2


def test_cancel_tool_accepts_explicitly_confirmed_mainnet(monkeypatch):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    monkeypatch.setenv("BOT_MAINNET_CANCEL_CONFIRMED", "YES")
    args = parse(monkeypatch, "--mainnet", "--live")
    assert args.testnet is False
    assert args.base_url == tools_cancel_open.DEFAULT_MAIN


def test_cancel_result_updates_matching_order_journal(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    intent = journal.prepare(
        client_order_id="LDBLAD-cancelled",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.126",
        price="75.80",
    )
    journal.record_exchange_order(
        intent.client_order_id,
        {"orderId": 17519304665, "status": "NEW", "executedQty": "0"},
    )

    updated = tools_cancel_open.record_order_result(
        journal,
        {
            "orderId": 17519304665,
            "clientOrderId": intent.client_order_id,
            "status": "CANCELED",
            "executedQty": "0.00000000",
        },
        {},
    )

    assert updated is not None
    assert updated.state == "CANCELED"
    assert journal.unresolved_buys("SOLUSDT") == []


def test_cancelled_partial_fill_still_requires_protection(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    intent = journal.prepare(
        client_order_id="LDBLAD-partial-cancel",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.126",
        price="75.80",
    )
    updated = tools_cancel_open.record_order_result(
        journal,
        {
            "orderId": 99,
            "clientOrderId": intent.client_order_id,
            "status": "CANCELED",
            "executedQty": "0.020",
            "cummulativeQuoteQty": "1.5",
        },
        {},
    )

    assert updated is not None
    assert updated.state == "PROTECTION_PENDING"
