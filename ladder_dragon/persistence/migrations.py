#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: apply versioned SQLite migrations.
"""Apply ordered, checksummed SQLite migrations."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3

from dotenv import load_dotenv

from ladder_dragon.persistence.sql_statements import execute_sql_script


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = PACKAGE_ROOT / "migrations"


def _is_pristine_database(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return True
    with sqlite3.connect(path, timeout=15) as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view','trigger') AND name NOT LIKE 'sqlite_%'"
            )
        }
    return not names


def _migration_files() -> tuple[tuple[str, Path], ...]:
    migrations = tuple(
        (migration.name.split("_", 1)[0], migration)
        for migration in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    )
    duplicates = sorted(
        version
        for version in {item[0] for item in migrations}
        if sum(item[0] == version for item in migrations) > 1
    )
    if duplicates:
        raise RuntimeError(
            "duplicate migration version(s): " + ", ".join(duplicates)
        )
    return migrations


def _apply_migration(
    connection: sqlite3.Connection,
    *,
    version: str,
    checksum: str,
    sql: str,
) -> None:
    """Apply schema and completion evidence in one crash-safe transaction."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        execute_sql_script(connection, sql, guard_existing_columns=True)
        connection.execute(
            "INSERT INTO schema_migrations(version, checksum) VALUES(?, ?)",
            (version, checksum),
        )
        connection.commit()
    except (RuntimeError, ValueError, sqlite3.Error):
        connection.rollback()
        raise


def migrate(db_path: str, *, exact_new_database: bool = True) -> list[str]:
    migrations = _migration_files()
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pristine = _is_pristine_database(path)
    applied_now: list[str] = []
    with sqlite3.connect(path, timeout=15) as con:
        con.execute("PRAGMA busy_timeout=7000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations(
              version TEXT PRIMARY KEY,
              checksum TEXT NOT NULL,
              applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        if pristine and exact_new_database:
            con.execute(
                "CREATE TABLE IF NOT EXISTS database_bootstrap("
                "target_storage TEXT PRIMARY KEY,completed INTEGER NOT NULL DEFAULT 0)"
            )
            con.execute(
                "INSERT OR IGNORE INTO database_bootstrap(target_storage,completed) "
                "VALUES('exact-accounting',0)"
            )
        applied = dict(con.execute("SELECT version, checksum FROM schema_migrations"))
        con.commit()
        for version, migration in migrations:
            sql = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise RuntimeError(f"migration {version} checksum changed after application")
                continue
            _apply_migration(
                con,
                version=version,
                checksum=checksum,
                sql=sql,
            )
            applied_now.append(version)
        has_risk_outcome_state = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='risk_sell_outcome_state'"
        ).fetchone()
        pending_risk_outcomes = (
            con.execute(
                "SELECT backfill_complete FROM risk_sell_outcome_state "
                "WHERE singleton=1"
            ).fetchone()
            if has_risk_outcome_state
            else None
        )
        if pending_risk_outcomes is not None and int(pending_risk_outcomes[0]) == 0:
            from ladder_dragon.risk.trade_streaks import rebuild_sell_outcomes

            con.execute("BEGIN IMMEDIATE")
            try:
                rebuild_sell_outcomes(con)
                con.commit()
            except (ArithmeticError, RuntimeError, ValueError, sqlite3.Error):
                con.rollback()
                raise
        pending_exact = bool(
            exact_new_database
            and con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='database_bootstrap'"
            ).fetchone()
            and con.execute(
                "SELECT 1 FROM database_bootstrap "
                "WHERE target_storage='exact-accounting' AND completed=0"
            ).fetchone()
        )
        if pending_exact:
            from ladder_dragon.execution.accounting_retirement import (
                bootstrap_exact_accounting_connection,
            )

            con.execute("BEGIN IMMEDIATE")
            try:
                bootstrap_exact_accounting_connection(con)
                con.execute(
                    "UPDATE database_bootstrap SET completed=1 "
                    "WHERE target_storage='exact-accounting'"
                )
                con.commit()
            except (RuntimeError, ValueError, sqlite3.Error):
                con.rollback()
                raise
        con.execute("PRAGMA optimize")
    return applied_now


def main() -> int:
    load_dotenv()
    db_path = os.getenv("BOT_STATS_DB", "").strip()
    if not db_path:
        raise SystemExit("BOT_STATS_DB is required")
    versions = migrate(db_path)
    print("Applied migrations:", ", ".join(versions) if versions else "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
