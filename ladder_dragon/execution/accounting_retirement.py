# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: retire binary-float accounting storage after a clean host audit.
"""Explicit, backed-up migration to the exact-only major-version schema."""

from __future__ import annotations

from pathlib import Path
import os
import sqlite3

from ladder_dragon.execution.compatibility_audit import (
    DEFAULT_LEGACY_PATHS,
    audit_compatibility,
)


TRADE_LEGACY_COLUMNS = frozenset({"price", "qty", "fee_quote"})
INVENTORY_LEGACY_COLUMNS = frozenset({"qty", "avg_cost", "realized_pnl"})


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def exact_only_schema(connection: sqlite3.Connection) -> bool:
    """Return true only when both financial tables have no legacy REAL fields."""
    return not (TRADE_LEGACY_COLUMNS & _columns(connection, "trades")) and not (
        INVENTORY_LEGACY_COLUMNS & _columns(connection, "inventory")
    )


def _create_exact_views(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE VIEW trades_exact AS
        SELECT id,symbol,side,price_text,
               gross_qty AS gross_qty_text,net_qty AS net_qty_text,
               commission_asset,
               commission_amount AS commission_amount_text,
               commission_quote AS commission_quote_text,
               commission_value_status,ts,trade_id
        FROM trades"""
    )
    connection.execute(
        """CREATE VIEW inventory_exact AS
        SELECT symbol,qty_text,avg_cost_text,realized_pnl_text,last_trade_id
        FROM inventory"""
    )


def _rebuild_exact_schema(connection: sqlite3.Connection) -> None:
    """Replace compatibility tables with exact-only accounting tables."""
    connection.executescript(
        """
        BEGIN IMMEDIATE;
        DROP VIEW IF EXISTS trades_exact;
        DROP VIEW IF EXISTS inventory_exact;
        DROP TRIGGER IF EXISTS trades_exact_after_insert;
        DROP TRIGGER IF EXISTS inventory_exact_after_insert;
        DROP TRIGGER IF EXISTS inventory_exact_after_legacy_update;

        CREATE TABLE trades_v3(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          symbol TEXT NOT NULL,
          side TEXT CHECK(side IN ('BUY','SELL')) NOT NULL,
          price_text TEXT NOT NULL CHECK(price_text != ''),
          gross_qty TEXT NOT NULL CHECK(gross_qty != ''),
          net_qty TEXT NOT NULL CHECK(net_qty != ''),
          commission_asset TEXT NOT NULL DEFAULT '',
          commission_amount TEXT NOT NULL DEFAULT '0',
          commission_quote TEXT,
          commission_value_status TEXT NOT NULL,
          ts INTEGER NOT NULL CHECK(ts > 0),
          trade_id INTEGER
        );
        INSERT INTO trades_v3(
          id,symbol,side,price_text,gross_qty,net_qty,
          commission_asset,commission_amount,commission_quote,
          commission_value_status,ts,trade_id
        )
        SELECT id,symbol,side,price_text,gross_qty,net_qty,
               commission_asset,commission_amount,commission_quote,
               commission_value_status,ts,trade_id
        FROM trades;

        CREATE TABLE inventory_v3(
          symbol TEXT PRIMARY KEY,
          qty_text TEXT NOT NULL DEFAULT '0',
          avg_cost_text TEXT NOT NULL DEFAULT '0',
          realized_pnl_text TEXT NOT NULL DEFAULT '0',
          last_trade_id INTEGER
        );
        INSERT INTO inventory_v3(
          symbol,qty_text,avg_cost_text,realized_pnl_text,last_trade_id
        )
        SELECT symbol,qty_text,avg_cost_text,realized_pnl_text,last_trade_id
        FROM inventory;

        DROP TABLE trades;
        ALTER TABLE trades_v3 RENAME TO trades;
        DROP TABLE inventory;
        ALTER TABLE inventory_v3 RENAME TO inventory;

        CREATE INDEX trades_idx ON trades(symbol,ts);
        CREATE INDEX trades_monthly_cover
          ON trades(symbol,ts,side,price_text,gross_qty,commission_quote);
        CREATE UNIQUE INDEX trades_sym_tradeid_uq
          ON trades(symbol,trade_id) WHERE trade_id IS NOT NULL;
        CREATE INDEX trades_accounting_cover
          ON trades(symbol,ts,side,price_text,gross_qty,net_qty);
        """
    )
    _create_exact_views(connection)


def bootstrap_exact_accounting_schema(database: Path) -> bool:
    """Make a newly migrated, empty database exact-only without a backup."""
    with sqlite3.connect(database, timeout=15) as connection:
        connection.execute("PRAGMA busy_timeout=7000")
        if exact_only_schema(connection):
            return False
        trade_count = int(connection.execute("SELECT COUNT(*) FROM trades").fetchone()[0])
        inventory_count = int(
            connection.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        )
        if trade_count or inventory_count:
            raise RuntimeError("exact bootstrap is restricted to empty accounting tables")
        try:
            _rebuild_exact_schema(connection)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity check failed after exact bootstrap")
            connection.commit()
        except (RuntimeError, sqlite3.Error):
            connection.rollback()
            raise
    return True


def retire_accounting_schema(database: Path, backup: Path) -> bool:
    """Remove legacy REAL fields only after a clean audit and online backup."""
    database = database.resolve()
    backup = backup.resolve()
    if database == backup:
        raise ValueError("backup path must differ from the statistics database")
    if backup.exists():
        raise FileExistsError(f"backup already exists: {backup}")
    report = audit_compatibility(database, legacy_paths=DEFAULT_LEGACY_PATHS)
    if not report.ready_for_major_removal:
        raise RuntimeError("compatibility audit is not clean: " + "; ".join(report.reasons))

    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database, timeout=15) as connection:
        if exact_only_schema(connection):
            return False
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)
        os.chmod(backup, 0o600)
        connection.execute("PRAGMA busy_timeout=7000")
        try:
            _rebuild_exact_schema(connection)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity check failed after retirement")
            if not exact_only_schema(connection):
                raise RuntimeError("legacy accounting columns remain after retirement")
            connection.commit()
        except (RuntimeError, sqlite3.Error):
            connection.rollback()
            raise
    return True
