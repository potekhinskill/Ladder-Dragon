#!/usr/bin/env python3
"""Apply ordered, checksummed SQLite migrations."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"


def migrate(db_path: str) -> list[str]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return applied_now


def main() -> int:
    db_path = os.getenv("BOT_STATS_DB", "").strip()
    if not db_path:
        raise SystemExit("BOT_STATS_DB is required")
    versions = migrate(db_path)
    print("Applied migrations:", ", ".join(versions) if versions else "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
