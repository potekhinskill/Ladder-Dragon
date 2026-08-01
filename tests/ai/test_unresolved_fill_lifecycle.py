# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify durable unresolved-fill review and late exact attribution.

import sqlite3
import sys

import pytest

from ladder_dragon.ai.context.decision_repository import AdvisorDecisionStore
from ladder_dragon.ai.unresolved_fills import lifecycle_counts
from ladder_dragon.ai.unresolved_review import review_unattributable_fills
from bin.review_unattributed_fills import main as review_main


REVIEW_NOTE = "historical_canary_without_decision_link"
CUTOFF = 2_000_000_000


def _journal(path, order_id: int = 12345) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE order_intents("
            "venue TEXT,symbol TEXT,exchange_order_id INTEGER)"
        )
        connection.execute(
            "CREATE TABLE order_intent_legs("
            "venue TEXT,symbol TEXT,order_id INTEGER)"
        )
        connection.execute(
            "INSERT INTO order_intents VALUES('mainnet','SOLUSDT',?)", (order_id,)
        )


def _pending(store: AdvisorDecisionStore, *, order_id: int = 12345) -> str:
    return store.record_unresolved_fill(
        symbol="SOLUSDT", side="BUY", price="77.33", qty="0.124",
        order_id=order_id, trade_id=88, ts=20,
        reason="exchange_order_id_not_mapped_to_decision",
    )


def test_review_preserves_evidence_without_inventing_decision_link(tmp_path):
    ai_path = tmp_path / "ai.db"
    journal_path = tmp_path / "journal.db"
    store = AdvisorDecisionStore(str(ai_path))
    fill_key = _pending(store)
    _journal(journal_path)

    assert review_unattributable_fills(
        ai_path, journal_path, note=REVIEW_NOTE,
        before_ts=CUTOFF, expected_count=1,
    ) == 1
    assert store.unresolved_fill_count() == 1

    reviewed = review_unattributable_fills(
        ai_path,
        journal_path, note=REVIEW_NOTE, before_ts=CUTOFF, expected_count=1,
        apply=True,
    )

    assert reviewed == 1
    assert store.unresolved_fill_count() == 0
    assert store.unresolved_fill_lifecycle_counts() == {
        "pending": 0,
        "reviewed_unattributable": 1,
        "resolved_linked": 0,
    }
    with sqlite3.connect(ai_path) as connection:
        row = connection.execute(
            "SELECT fill_key,resolution_status,resolution_note,"
            "resolved_decision_id FROM ai_unresolved_fills"
        ).fetchone()
        links = connection.execute("SELECT COUNT(*) FROM ai_order_links").fetchone()[0]
        fills = connection.execute("SELECT COUNT(*) FROM ai_fills").fetchone()[0]
    assert row == (fill_key, "REVIEWED_UNATTRIBUTABLE", REVIEW_NOTE, None)
    assert links == 0
    assert fills == 0


def test_review_fails_closed_without_exact_journal_proof(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    _pending(store)
    journal_path = tmp_path / "journal.db"
    _journal(journal_path, order_id=99999)

    with pytest.raises(RuntimeError, match="does not prove"):
        review_unattributable_fills(
            tmp_path / "ai.db",
            journal_path, note=REVIEW_NOTE, before_ts=CUTOFF, expected_count=1
        )

    assert store.unresolved_fill_count() == 1


def test_reviewed_fill_resolves_when_an_exact_link_arrives(tmp_path):
    ai_path = tmp_path / "ai.db"
    journal_path = tmp_path / "journal.db"
    store = AdvisorDecisionStore(str(ai_path))
    _pending(store)
    _journal(journal_path)
    review_unattributable_fills(
        ai_path,
        journal_path, note=REVIEW_NOTE, before_ts=CUTOFF, expected_count=1,
        apply=True,
    )
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=False,
    )

    store.link_client_order(
        "exact-client", decision, symbol="SOLUSDT", exchange_order_id=12345
    )

    counts = store.unresolved_fill_lifecycle_counts()
    assert counts["pending"] == 0
    assert counts["reviewed_unattributable"] == 0
    assert counts["resolved_linked"] == 1
    with sqlite3.connect(ai_path) as connection:
        row = connection.execute(
            "SELECT resolution_status,resolved_decision_id "
            "FROM ai_unresolved_fills"
        ).fetchone()
    assert row == ("RESOLVED_LINKED", decision)


def test_inventory_scope_cannot_be_reviewed_as_attribution(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    store.record_unresolved_fill(
        symbol="SOLUSDT", side="BUY", price="77.33", qty="0.124",
        order_id=12345, trade_id=88, ts=20, resolution_scope="INVENTORY",
    )
    journal_path = tmp_path / "journal.db"
    _journal(journal_path)

    with pytest.raises(RuntimeError, match="count differs"):
        review_unattributable_fills(
            tmp_path / "ai.db",
            journal_path, note=REVIEW_NOTE, before_ts=CUTOFF, expected_count=1
        )

    assert store.unresolved_fill_count_by_scope("INVENTORY") == 1


def test_review_note_cannot_persist_untrusted_operator_text(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    _pending(store)
    journal_path = tmp_path / "journal.db"
    _journal(journal_path)

    with pytest.raises(ValueError, match="approved classification"):
        review_unattributable_fills(
            tmp_path / "ai.db", journal_path,
            note="signature=must-not-be-stored", before_ts=CUTOFF,
            expected_count=1, apply=True,
        )

    assert store.unresolved_fill_count() == 1


def test_unknown_lifecycle_status_remains_inventory_blocking(tmp_path):
    path = tmp_path / "damaged.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE ai_unresolved_fills("
            "resolution_scope TEXT,resolution_status TEXT)"
        )
        connection.execute(
            "INSERT INTO ai_unresolved_fills VALUES('ATTRIBUTION','DAMAGED')"
        )
        counts = lifecycle_counts(connection)

    assert counts["pending"] == 1
    assert counts["attribution"] == 0
    assert counts["inventory"] == 1


def test_cli_preview_does_not_migrate_or_mutate_ai_database(
    tmp_path, monkeypatch, capsys
):
    ai_path = tmp_path / "preview.db"
    journal_path = tmp_path / "journal.db"
    with sqlite3.connect(ai_path) as connection:
        connection.execute(
            "CREATE TABLE ai_unresolved_fills("
            "fill_key TEXT,symbol TEXT,order_id TEXT,resolution_scope TEXT,"
            "resolution_status TEXT,reason TEXT,created_at INTEGER)"
        )
        connection.execute(
            "INSERT INTO ai_unresolved_fills VALUES("
            "'one','SOLUSDT','12345','ATTRIBUTION','PENDING',"
            "'exchange_order_id_not_mapped_to_decision',1)"
        )
        connection.execute(
            "CREATE TABLE ai_order_links(exchange_order_id TEXT)"
        )
    _journal(journal_path)
    monkeypatch.setattr(sys, "argv", [
        "review_unattributed_fills", "--ai-db", str(ai_path),
        "--journal", str(journal_path), "--note", REVIEW_NOTE,
        "--before-ts", str(CUTOFF), "--expected-count", "1",
    ])

    assert review_main() == 0

    assert "candidates=1" in capsys.readouterr().out
    with sqlite3.connect(ai_path) as connection:
        tables = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        status = connection.execute(
            "SELECT resolution_status FROM ai_unresolved_fills"
        ).fetchone()[0]
    assert tables == {"ai_unresolved_fills", "ai_order_links"}
    assert status == "PENDING"
