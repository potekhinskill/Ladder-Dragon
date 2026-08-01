# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: classify durable unresolved-fill evidence without weakening safety gates.

"""Status-aware unresolved-fill queries for read-only gates and telemetry."""

from __future__ import annotations

import sqlite3


def record_pending_fill(
    connection: sqlite3.Connection, *, fill_key: str, symbol: str, side: str,
    order_id: str | None, trade_id: str | None, price: str, qty: str,
    fee_quote: str, ts: int, reason: str, scope: str, created_at: int,
) -> None:
    """Upsert evidence without reopening a reviewed attribution gap."""
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
