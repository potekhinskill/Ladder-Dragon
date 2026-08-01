# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: review journal-proven AI attribution gaps without inventing links.

"""Transactional operator review for historical AI attribution gaps."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time


REVIEW_NOTES = frozenset({"historical_canary_without_decision_link"})


def review_unattributable_fills(
    ai_path: str | Path,
    journal_path: str | Path,
    *,
    note: str,
    before_ts: int,
    expected_count: int,
    apply: bool = False,
) -> int:
    """Review only an exact, journal-proven, unlinked historical set."""
    review_note = str(note).strip()
    if review_note not in REVIEW_NOTES:
        raise ValueError("review note is not an approved classification")
    journal = Path(journal_path)
    if not journal.is_file():
        raise FileNotFoundError(journal)
    if before_ts <= 0 or expected_count <= 0:
        raise ValueError("review cutoff and expected count must be positive")
    with sqlite3.connect(
        f"file:{journal}?mode=ro", uri=True, timeout=5
    ) as proof:
        tables = {
            str(row[0]) for row in proof.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"order_intents", "order_intent_legs"}.issubset(tables):
            raise ValueError("order journal proof tables are missing")
        proven = {
            (str(row[0]).upper(), str(row[1])) for row in proof.execute(
                "SELECT symbol,CAST(exchange_order_id AS TEXT) "
                "FROM order_intents WHERE venue='mainnet' "
                "AND exchange_order_id IS NOT NULL UNION "
                "SELECT symbol,CAST(order_id AS TEXT) "
                "FROM order_intent_legs WHERE venue='mainnet'"
            )
        }
    ai_target: str | Path = Path(ai_path)
    if not apply:
        ai_target = f"file:{Path(ai_path)}?mode=ro"
    with sqlite3.connect(ai_target, uri=not apply, timeout=5) as connection:
        connection.execute("PRAGMA busy_timeout=5000")
        if apply:
            connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT fill_key,symbol,order_id FROM ai_unresolved_fills "
            "WHERE resolution_scope='ATTRIBUTION' "
            "AND reason='exchange_order_id_not_mapped_to_decision' "
            "AND resolution_status='PENDING' AND created_at<=?",
            (before_ts,),
        ).fetchall()
        if len(rows) != expected_count:
            raise RuntimeError("pending attribution count differs from approval")
        if any(row[2] is None for row in rows):
            raise ValueError("an attribution fill has no exchange order identifier")
        order_ids = {str(row[2]) for row in rows}
        linked = {
            str(row[0]) for row in connection.execute(
                "SELECT exchange_order_id FROM ai_order_links "
                "WHERE exchange_order_id IS NOT NULL"
            )
        }
        if order_ids & linked:
            raise RuntimeError("an exact AI order link already exists")
        missing = {
            (str(row[1]).upper(), str(row[2])) for row in rows
        } - proven
        if missing:
            raise RuntimeError("the order journal does not prove every fill")
        if not apply:
            return len(rows)
        stamp = int(time.time())
        updated = connection.execute(
            "UPDATE ai_unresolved_fills SET "
            "resolution_status='REVIEWED_UNATTRIBUTABLE',"
            "resolution_note=?,reviewed_at=?,resolution_updated_at=? "
            "WHERE resolution_scope='ATTRIBUTION' "
            "AND reason='exchange_order_id_not_mapped_to_decision' "
            "AND resolution_status='PENDING' AND created_at<=?",
            (review_note, stamp, stamp, before_ts),
        ).rowcount
        if updated != len(rows):
            raise RuntimeError("attribution review changed concurrently")
        return int(updated)
