#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: apply database index migrations.
import os
import sqlite3

DB = os.getenv('BOT_STATS_DB', '/home/bot/apps/binance_bot/db/bot_stats.db')

EXACT_MONTHLY_COLUMNS = (
    "symbol",
    "ts",
    "side",
    "price_text",
    "gross_qty",
    "commission_quote",
)
LEGACY_MONTHLY_COLUMNS = ("symbol", "ts", "side", "price", "qty", "fee_quote")

def table_exists(con: sqlite3.Connection, name: str) -> bool:
    cur = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,))
    return cur.fetchone() is not None


def _table_columns(con: sqlite3.Connection, name: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{name}")')}


def index_statements(con: sqlite3.Connection) -> tuple[str, str]:
    """Select index definitions for the authoritative trades schema."""
    columns = _table_columns(con, "trades")
    if set(EXACT_MONTHLY_COLUMNS).issubset(columns):
        monthly_columns = EXACT_MONTHLY_COLUMNS
    elif set(LEGACY_MONTHLY_COLUMNS).issubset(columns):
        monthly_columns = LEGACY_MONTHLY_COLUMNS
    else:
        raise RuntimeError("trades schema cannot support the monthly covering index")
    monthly = (
        "CREATE INDEX IF NOT EXISTS trades_monthly_cover ON trades("
        + ", ".join(monthly_columns)
        + ");"
    )
    unique = (
        "CREATE UNIQUE INDEX IF NOT EXISTS trades_sym_tradeid_uq "
        "ON trades(symbol, trade_id) WHERE trade_id IS NOT NULL;"
    )
    return monthly, unique

def main() -> int:
    # Open the connection and set a lock timeout.
    with sqlite3.connect(DB, timeout=15.0) as con:
        con.execute("PRAGMA busy_timeout=7000;")
        # If the table is absent, exit gracefully.
        if not table_exists(con, 'trades'):
            print(f"[SKIP] no table 'trades' yet in {DB} — nothing to index")
            return 0

        cur = con.cursor()
        for sql in index_statements(con):
            cur.execute(sql)
            idx_name = sql.split(" IF NOT EXISTS ")[-1].split()[0]
            print(f"[IDX] {idx_name} ok")

        # Refresh optimizer statistics.
        cur.executescript("ANALYZE; PRAGMA optimize;")
        print("[OK] migrate_indexes done on", DB)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
