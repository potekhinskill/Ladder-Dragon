# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: classify durable unresolved-fill evidence without weakening safety gates.

"""Status-aware unresolved-fill queries for read-only gates and telemetry."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import sqlite3


def create_unresolved_fill_table(connection: sqlite3.Connection) -> None:
    """Create the exact unresolved-fill evidence table."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS ai_unresolved_fills(
            fill_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
            order_id TEXT, trade_id TEXT,
            price TEXT NOT NULL CHECK(price != '' AND price=price_text),
            qty TEXT NOT NULL CHECK(qty != '' AND qty=qty_text),
            fee_quote TEXT NOT NULL DEFAULT '0'
                CHECK(fee_quote != '' AND fee_quote=fee_quote_text),
            price_text TEXT NOT NULL, qty_text TEXT NOT NULL,
            fee_quote_text TEXT NOT NULL, ts INTEGER NOT NULL,
            reason TEXT NOT NULL,
            resolution_scope TEXT NOT NULL DEFAULT 'ATTRIBUTION',
            resolution_status TEXT NOT NULL DEFAULT 'PENDING',
            resolution_note TEXT NOT NULL DEFAULT '',
            reviewed_at INTEGER,
            resolved_decision_id TEXT,
            resolution_updated_at INTEGER,
            created_at INTEGER NOT NULL
        )"""
    )


def ensure_exact_amount_storage(connection: sqlite3.Connection) -> None:
    """Replace legacy REAL amount affinity with exact TEXT storage."""
    affinities = {
        str(row[1]): str(row[2]).upper()
        for row in connection.execute("PRAGMA table_info(ai_unresolved_fills)")
    }
    amount_columns = {"price", "qty", "fee_quote"}
    if not amount_columns.issubset(affinities):
        raise ValueError("unresolved fill amount columns are missing")
    if all(affinities[column] == "TEXT" for column in amount_columns):
        return

    shadow_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='ai_unresolved_fills_exact'"
    ).fetchone()
    if shadow_exists:
        raise RuntimeError("unresolved fill migration table already exists")
    connection.execute(
        """CREATE TABLE ai_unresolved_fills_exact(
            fill_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
            order_id TEXT, trade_id TEXT,
            price TEXT NOT NULL CHECK(price != '' AND price=price_text),
            qty TEXT NOT NULL CHECK(qty != '' AND qty=qty_text),
            fee_quote TEXT NOT NULL DEFAULT '0'
                CHECK(fee_quote != '' AND fee_quote=fee_quote_text),
            price_text TEXT NOT NULL, qty_text TEXT NOT NULL,
            fee_quote_text TEXT NOT NULL, ts INTEGER NOT NULL,
            reason TEXT NOT NULL,
            resolution_scope TEXT NOT NULL DEFAULT 'ATTRIBUTION',
            resolution_status TEXT NOT NULL DEFAULT 'PENDING',
            resolution_note TEXT NOT NULL DEFAULT '',
            reviewed_at INTEGER,
            resolved_decision_id TEXT,
            resolution_updated_at INTEGER,
            created_at INTEGER NOT NULL
        )"""
    )
    rows = connection.execute(
        """SELECT fill_key,symbol,side,order_id,trade_id,
            price,qty,fee_quote,price_text,qty_text,fee_quote_text,
            ts,reason,resolution_scope,resolution_status,resolution_note,
            reviewed_at,resolved_decision_id,resolution_updated_at,created_at
        FROM ai_unresolved_fills"""
    )
    for row in rows:
        try:
            exact = tuple(
                str(row[text_index])
                if row[text_index] not in (None, "")
                else format(row[value_index], ".17g")
                for value_index, text_index in ((5, 8), (6, 9), (7, 10))
            )
            if any(not Decimal(value).is_finite() for value in exact):
                raise ValueError
        except (InvalidOperation, TypeError, ValueError) as exc:
            # Do not include evidence values in this error. They can contain
            # incident data that must not enter deployment logs.
            raise ValueError(
                "unresolved fill monetary evidence is invalid"
            ) from exc
        connection.execute(
            """INSERT INTO ai_unresolved_fills_exact(
                fill_key,symbol,side,order_id,trade_id,price,qty,fee_quote,
                price_text,qty_text,fee_quote_text,ts,reason,resolution_scope,
                resolution_status,resolution_note,reviewed_at,
                resolved_decision_id,resolution_updated_at,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*row[:5], *exact, *exact, *row[11:]),
        )
    connection.execute("DROP TABLE ai_unresolved_fills")
    connection.execute(
        "ALTER TABLE ai_unresolved_fills_exact RENAME TO ai_unresolved_fills"
    )


def record_pending_fill(
    connection: sqlite3.Connection, *, fill_key: str, symbol: str, side: str,
    order_id: str | None, trade_id: str | None, price: str, qty: str,
    fee_quote: str, ts: int, reason: str, scope: str, created_at: int,
) -> None:
    """Upsert evidence without reopening a reviewed attribution gap."""
    # The primary and companion columns remain for rollback compatibility.
    # Both columns use TEXT affinity and an equality constraint.
    connection.execute(
        """INSERT INTO ai_unresolved_fills(
            fill_key,symbol,side,order_id,trade_id,price,qty,fee_quote,
            price_text,qty_text,fee_quote_text,ts,reason,
            resolution_scope,resolution_status,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(fill_key) DO UPDATE SET
            symbol=excluded.symbol,side=excluded.side,
            order_id=excluded.order_id,trade_id=excluded.trade_id,
            price=excluded.price,qty=excluded.qty,fee_quote=excluded.fee_quote,
            price_text=excluded.price_text,qty_text=excluded.qty_text,
            fee_quote_text=excluded.fee_quote_text,ts=excluded.ts,
            reason=excluded.reason,resolution_scope=excluded.resolution_scope,
            resolution_status=CASE WHEN excluded.resolution_scope='INVENTORY'
              THEN 'PENDING' ELSE ai_unresolved_fills.resolution_status END,
            resolution_note=CASE WHEN excluded.resolution_scope='INVENTORY'
              THEN '' ELSE ai_unresolved_fills.resolution_note END,
            reviewed_at=CASE WHEN excluded.resolution_scope='INVENTORY'
              THEN NULL ELSE ai_unresolved_fills.reviewed_at END""",
        (
            fill_key, symbol, side, order_id, trade_id, price, qty, fee_quote,
            price, qty, fee_quote, ts, reason[:240], scope, "PENDING", created_at,
        ),
    )


def lifecycle_counts(
    connection: sqlite3.Connection, *, symbol: str | None = None
) -> dict[str, int]:
    """Treat legacy and unknown rows as pending inventory risk."""
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(ai_unresolved_fills)")
    }
    where = ""
    params: tuple[str, ...] = ()
    if symbol is not None:
        if "symbol" not in columns:
            raise ValueError("unresolved fill symbol column is missing")
        where = " WHERE symbol=?"
        params = (symbol.upper(),)
    total = int(connection.execute(
        "SELECT COUNT(*) FROM ai_unresolved_fills" + where, params
    ).fetchone()[0])
    if "resolution_scope" not in columns:
        return {
            "total": total,
            "pending": total,
            "attribution": 0,
            "inventory": total,
            "reviewed_unattributable": 0,
            "resolved_linked": 0,
        }
    if "resolution_status" not in columns:
        prefix = " WHERE " if not where else where + " AND "
        attribution = int(connection.execute(
            "SELECT COUNT(*) FROM ai_unresolved_fills" + prefix
            + "resolution_scope='ATTRIBUTION'",
            params,
        ).fetchone()[0])
        return {
            "total": total,
            "pending": total,
            "attribution": attribution,
            "inventory": total - attribution,
            "reviewed_unattributable": 0,
            "resolved_linked": 0,
        }
    prefix = " WHERE " if not where else where + " AND "
    pending_clause = (
        "(resolution_status='PENDING' OR resolution_status IS NULL "
        "OR resolution_status NOT IN "
        "('PENDING','REVIEWED_UNATTRIBUTABLE','RESOLVED_LINKED'))"
    )
    pending = int(connection.execute(
        "SELECT COUNT(*) FROM ai_unresolved_fills" + prefix + pending_clause,
        params,
    ).fetchone()[0])
    attribution = int(connection.execute(
        "SELECT COUNT(*) FROM ai_unresolved_fills" + prefix
        + "resolution_status='PENDING' AND resolution_scope='ATTRIBUTION'",
        params,
    ).fetchone()[0])
    inventory = pending - attribution
    reviewed = int(connection.execute(
        "SELECT COUNT(*) FROM ai_unresolved_fills" + prefix
        + "resolution_status='REVIEWED_UNATTRIBUTABLE'",
        params,
    ).fetchone()[0])
    resolved = int(connection.execute(
        "SELECT COUNT(*) FROM ai_unresolved_fills" + prefix
        + "resolution_status='RESOLVED_LINKED'",
        params,
    ).fetchone()[0])
    return {
        "total": total,
        "pending": pending,
        "attribution": attribution,
        "inventory": inventory,
        "reviewed_unattributable": reviewed,
        "resolved_linked": resolved,
    }
