# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: isolate prediction readers from writers without weakening durability.
"""Prediction-only WAL policy; no schema changes, retries, or evidence deletion."""

from contextlib import closing
from pathlib import Path
import sqlite3


def prepare_prediction_database(path: str | Path) -> Path:
    """Enable persistent WAL before migrations, or reject initialization."""
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        if mode != ("wal",):
            raise sqlite3.OperationalError("prediction WAL mode unavailable")
    return database


def connect_prediction_database(path: Path) -> sqlite3.Connection:
    """Keep writer limits and FULL durability; never silently revert to DELETE."""
    connection = sqlite3.connect(path, timeout=10)
    try:
        if connection.execute("PRAGMA journal_mode").fetchone() != ("wal",):
            raise sqlite3.OperationalError("prediction WAL mode changed")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA wal_autocheckpoint=1000")
        return connection
    except sqlite3.Error:
        connection.close()
        raise
