# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: centralize bounded read-only SQLite connections for dashboard routes.

"""Dashboard dependencies."""

import sqlite3
from pathlib import Path


def open_read_only_sqlite(path: str | Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    """Open an existing SQLite database without granting write access."""
    target = Path(path).resolve()
    connection = sqlite3.connect(
        f"file:{target}?mode=ro",
        uri=True,
        timeout=max(1.0, float(timeout)),
    )
    connection.row_factory = sqlite3.Row
    return connection
