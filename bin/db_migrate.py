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


ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "ladder_dragon" / "migrations"


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


def migrate(db_path: str, *, exact_new_database: bool = True) -> list[str]:
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
        for migration in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
            version = migration.name.split("_", 1)[0]
            sql = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise RuntimeError(f"migration {version} checksum changed after application")
                continue
            con.executescript(sql)
            con.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES(?, ?)",
                (version, checksum),
            )
            applied_now.append(version)
        con.execute("PRAGMA optimize")
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
            bootstrap_exact_accounting_schema,
        )

        bootstrap_exact_accounting_schema(path)
        with sqlite3.connect(path, timeout=15) as con:
            con.execute(
                "UPDATE database_bootstrap SET completed=1 "
                "WHERE target_storage='exact-accounting'"
            )
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
