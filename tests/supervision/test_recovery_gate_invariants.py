"""Fail-closed startup recovery classification and HALT regressions."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from ladder_dragon.supervision.entry_policy import finite_decimal
from ladder_dragon.supervision import recovery_gate


class MissingOrder(RuntimeError):
    """Represent one structured Binance missing-order response."""

    code = -2013


def _runtime(journal, signed_get, halts):
    return {
        "OrderJournal": lambda _path, venue: journal,
        "TM": SimpleNamespace(_signed_get=signed_get),
        "SUPERVISOR_OPERATION_ERRORS": (
            RuntimeError,
            requests.RequestException,
        ),
        "_finite_decimal": finite_decimal,
        "_create_manual_halt_once": (
            lambda reason, **kwargs: halts.append((reason, kwargs))
        ),
        "_verify_all_live_protection": lambda *_args: 0,
        "_exchange_order_absent": recovery_gate.exchange_order_absent,
    }


def _args():
    return SimpleNamespace(live=True, testnet=False)


def test_missing_order_classifier_uses_exact_code_and_wrapped_causes():
    wrapped = RuntimeError("outer")
    wrapped.__cause__ = MissingOrder("inner")
    assert recovery_gate.exchange_order_absent(MissingOrder("missing"))
    assert recovery_gate.exchange_order_absent(wrapped)
    assert recovery_gate.exchange_order_absent(
        RuntimeError("Binance {'code': -2013}")
    )
    assert not recovery_gate.exchange_order_absent(
        RuntimeError("Binance code=-20130")
    )


def test_missing_submitted_order_creates_durable_halt(monkeypatch):
    intent = SimpleNamespace(
        symbol="SOLUSDT",
        client_order_id="submitted-order",
        side="BUY",
        state="SUBMITTED",
    )
    journal = SimpleNamespace(nonterminal_orders=lambda: [intent])
    halts = []
    monkeypatch.setenv("BOT_ORDER_JOURNAL", "/isolated/orders.sqlite3")

    with pytest.raises(RuntimeError, match="cannot find durable BUY"):
        recovery_gate.pre_running_recovery_gate(
            _args(),
            ["SOLUSDT"],
            runtime=_runtime(
                journal,
                lambda *_args: (_ for _ in ()).throw(MissingOrder()),
                halts,
            ),
        )

    assert halts[0][1]["metadata"] == {
        "gate": "startup_missing_durable_order",
        "symbol": "SOLUSDT",
        "client_order_id": "submitted-order",
        "journal_state": "SUBMITTED",
    }


def test_removed_symbol_creates_durable_halt_before_exchange_read(monkeypatch):
    intent = SimpleNamespace(
        symbol="ETHUSDT",
        client_order_id="removed-symbol-order",
        side="BUY",
        state="PREPARED",
    )
    journal = SimpleNamespace(nonterminal_orders=lambda: [intent])
    halts = []
    exchange_reads = []
    monkeypatch.setenv("BOT_ORDER_JOURNAL", "/isolated/orders.sqlite3")

    with pytest.raises(RuntimeError, match="outside configuration"):
        recovery_gate.pre_running_recovery_gate(
            _args(),
            ["SOLUSDT"],
            runtime=_runtime(
                journal,
                lambda *_args: exchange_reads.append(True),
                halts,
            ),
        )

    assert exchange_reads == []
    assert halts[0][1]["metadata"]["gate"] == (
        "startup_journal_symbol_mismatch"
    )


def test_invalid_executed_quantity_creates_durable_halt(monkeypatch):
    buy = SimpleNamespace(
        symbol="SOLUSDT",
        client_order_id="damaged-buy",
        executed_qty="not-a-number",
    )
    journal = SimpleNamespace(
        nonterminal_orders=lambda: [],
        unresolved_buys=lambda: [buy],
    )
    halts = []
    monkeypatch.setenv("BOT_ORDER_JOURNAL", "/isolated/orders.sqlite3")

    with pytest.raises(RuntimeError, match="invalid executed quantity"):
        recovery_gate.pre_running_recovery_gate(
            _args(),
            ["SOLUSDT"],
            runtime=_runtime(journal, lambda *_args: {}, halts),
        )

    assert halts[0][1]["metadata"] == {
        "gate": "startup_invalid_executed_quantity",
        "symbol": "SOLUSDT",
        "client_order_id": "damaged-buy",
    }


def test_invalid_exchange_payload_creates_durable_halt(monkeypatch):
    intent = SimpleNamespace(
        symbol="SOLUSDT",
        client_order_id="invalid-response-order",
        side="BUY",
        state="PREPARED",
    )

    class Journal:
        @staticmethod
        def nonterminal_orders():
            return [intent]

        @staticmethod
        def record_exchange_order(_client_order_id, _payload):
            raise ValueError("invalid exchange order fields")

    halts = []
    monkeypatch.setenv("BOT_ORDER_JOURNAL", "/isolated/orders.sqlite3")

    with pytest.raises(RuntimeError, match="cannot update"):
        recovery_gate.pre_running_recovery_gate(
            _args(),
            ["SOLUSDT"],
            runtime=_runtime(Journal(), lambda *_args: {"status": "NEW"}, halts),
        )

    assert halts[0][1]["metadata"]["gate"] == (
        "startup_invalid_order_response"
    )


def test_transient_exchange_read_does_not_create_persistent_halt(monkeypatch):
    intent = SimpleNamespace(
        symbol="SOLUSDT",
        client_order_id="transient-order",
        side="BUY",
        state="SUBMITTED",
    )
    journal = SimpleNamespace(nonterminal_orders=lambda: [intent])
    halts = []
    monkeypatch.setenv("BOT_ORDER_JOURNAL", "/isolated/orders.sqlite3")

    with pytest.raises(RuntimeError, match="reconciliation failed"):
        recovery_gate.pre_running_recovery_gate(
            _args(),
            ["SOLUSDT"],
            runtime=_runtime(
                journal,
                lambda *_args: (_ for _ in ()).throw(
                    requests.Timeout("temporary read failure")
                ),
                halts,
            ),
        )

    assert halts == []


def test_corrupt_halt_marker_is_archived_before_replacement(
    tmp_path,
    monkeypatch,
):
    halt_path = tmp_path / "circuit_halt.json"
    damaged = b'{"reasons":["original evidence"'
    halt_path.write_bytes(damaged)
    created = []
    monkeypatch.setattr(
        recovery_gate,
        "create_manual_halt",
        lambda reason, **kwargs: created.append((reason, kwargs)),
    )

    recovery_gate.create_manual_halt_once(
        "replacement reason",
        limits=SimpleNamespace(halt_file=halt_path),
        metadata={"gate": "test"},
    )

    archives = list(tmp_path.glob("circuit_halt.json.corrupt-*"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == damaged
    assert archives[0].stat().st_mode & 0o777 == 0o600
    assert created[0][0] == "replacement reason"


def test_invalid_halt_schema_is_archived_before_replacement(
    tmp_path,
    monkeypatch,
):
    halt_path = tmp_path / "circuit_halt.json"
    damaged = b'{"reasons":"not-a-list"}'
    halt_path.write_bytes(damaged)
    monkeypatch.setattr(
        recovery_gate,
        "create_manual_halt",
        lambda *_args, **_kwargs: None,
    )

    recovery_gate.create_manual_halt_once(
        "replacement reason",
        limits=SimpleNamespace(halt_file=halt_path),
        metadata={"gate": "test"},
    )

    archives = list(tmp_path.glob("circuit_halt.json.corrupt-*"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == damaged
