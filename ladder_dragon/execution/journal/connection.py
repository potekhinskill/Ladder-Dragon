# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: configure durable process-local order-journal connections.

"""SQLite connection policy for the order journal."""

import sqlite3
from pathlib import Path


def connect_journal(path: str | Path) -> sqlite3.Connection:
    """Open one durable journal connection with fail-closed settings."""
    connection = sqlite3.connect(
        Path(path),
        timeout=10,
        check_same_thread=False,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection
