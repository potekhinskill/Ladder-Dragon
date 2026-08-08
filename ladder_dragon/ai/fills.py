# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own exact AI fill storage and slippage provenance.

"""Exact storage primitives for attributed AI fills."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import sqlite3


SLIPPAGE_VALUE_STATUSES = frozenset({
    "exact", "unavailable", "legacy_unverified",
})


def normalize_exchange_fill_identity(
    order_id: object | None, trade_id: object | None,
) -> tuple[str | None, str | None]:
    """Require a complete Binance identity when either identifier is present."""
    supplied = order_id is not None or trade_id is not None
    normalized_order = str(order_id).strip() if order_id is not None else ""
    normalized_trade = str(trade_id).strip() if trade_id is not None else ""
    if supplied and not (normalized_order and normalized_trade):
        raise ValueError("exchange fill requires order_id and trade_id")
    return (
        normalized_order if supplied else None,
        normalized_trade if supplied else None,
    )


def create_ai_fill_table(connection: sqlite3.Connection) -> None:
    """Create the exact attributed-fill evidence table."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS ai_fills(
            fill_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL,
            symbol TEXT NOT NULL, side TEXT NOT NULL,
            price TEXT NOT NULL CHECK(price != '' AND price=price_text),
            qty TEXT NOT NULL CHECK(qty != '' AND qty=qty_text),
            fee_quote TEXT NOT NULL DEFAULT '0'
                CHECK(fee_quote != '' AND fee_quote=fee_quote_text),
            price_text TEXT NOT NULL, qty_text TEXT NOT NULL,
            fee_quote_text TEXT NOT NULL,
            exit_reason TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL,
            order_id TEXT, trade_id TEXT, client_order_id TEXT,
            order_list_id TEXT, leg_type TEXT NOT NULL DEFAULT '',
            link_status TEXT NOT NULL DEFAULT 'resolved',
            slippage_quote TEXT NOT NULL DEFAULT '0'
                CHECK(slippage_quote != '' AND slippage_quote=slippage_quote_text),
            slippage_quote_text TEXT NOT NULL,
            slippage_value_status TEXT NOT NULL DEFAULT 'unavailable'
                CHECK(slippage_value_status IN
                    ('exact','unavailable','legacy_unverified')),
            FOREIGN KEY(decision_id) REFERENCES ai_decisions(decision_id)
        )"""
    )


def _exact_value(value: object, companion: object) -> str:
    """Preserve exact text or round-trip one legacy SQLite double."""
    raw = str(companion) if companion not in (None, "") else format(value, ".17g")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("AI fill monetary evidence is invalid") from exc
    if not parsed.is_finite():
        raise ValueError("AI fill monetary evidence is invalid")
    return raw


def ensure_exact_ai_fill_storage(connection: sqlite3.Connection) -> None:
    """Migrate attributed fills to exact amounts and explicit provenance."""
    columns = {
        str(row[1]): str(row[2]).upper()
        for row in connection.execute("PRAGMA table_info(ai_fills)")
    }
    amount_columns = {"price", "qty", "fee_quote", "slippage_quote"}
    if not amount_columns.issubset(columns):
        raise ValueError("AI fill amount columns are missing")
    table_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_fills'"
    ).fetchone()
    table_sql = str(table_sql_row[0] or "") if table_sql_row else ""
    exact_schema = (
        all(columns[column] == "TEXT" for column in amount_columns)
        and "price=price_text" in table_sql
        and "slippage_quote=slippage_quote_text" in table_sql
        and "slippage_value_status" in columns
    )
    if exact_schema:
        return

    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='ai_fills_exact'"
    ).fetchone():
        raise RuntimeError("AI fill migration table already exists")

    connection.execute("ALTER TABLE ai_fills RENAME TO ai_fills_legacy")
    create_ai_fill_table(connection)
    legacy_columns = {
        str(row[1]) for row in connection.execute(
            "PRAGMA table_info(ai_fills_legacy)"
        )
    }
    has_status = "slippage_value_status" in legacy_columns
    status_select = "slippage_value_status" if has_status else "NULL"
    rows = connection.execute(
        "SELECT fill_id,decision_id,symbol,side,price,qty,fee_quote,"
        "price_text,qty_text,fee_quote_text,exit_reason,ts,order_id,trade_id,"
        "client_order_id,order_list_id,leg_type,link_status,slippage_quote,"
        f"slippage_quote_text,{status_select} FROM ai_fills_legacy"
    )
    for row in rows:
        exact = tuple(
            _exact_value(row[value_index], row[text_index])
            for value_index, text_index in ((4, 7), (5, 8), (6, 9), (18, 19))
        )
        status = str(row[20] or "legacy_unverified").strip().lower()
        if status not in SLIPPAGE_VALUE_STATUSES:
            raise ValueError("AI fill slippage provenance is invalid")
        connection.execute(
            """INSERT INTO ai_fills(
                fill_id,decision_id,symbol,side,price,qty,fee_quote,
                price_text,qty_text,fee_quote_text,exit_reason,ts,order_id,
                trade_id,client_order_id,order_list_id,leg_type,link_status,
                slippage_quote,slippage_quote_text,slippage_value_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*row[:4], *exact[:3], *exact[:3], *row[10:18], exact[3], exact[3], status),
        )
    connection.execute("DROP TABLE ai_fills_legacy")
