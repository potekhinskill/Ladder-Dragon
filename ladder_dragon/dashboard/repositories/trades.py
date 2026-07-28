# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: read trade rows without granting dashboard write access.

"""Read-only trade repository."""

import sqlite3
from collections.abc import Sequence


def load_trade_rows(
    connection: sqlite3.Connection,
    *,
    symbols: Sequence[str] | None = None,
) -> list[sqlite3.Row]:
    """Load ordered trades with parameterized symbol filtering."""
    if not symbols:
        return list(connection.execute("SELECT * FROM trades ORDER BY time ASC, id ASC"))
    placeholders = ",".join("?" for _ in symbols)
    return list(
        connection.execute(
            f"SELECT * FROM trades WHERE symbol IN ({placeholders}) "
            "ORDER BY time ASC, id ASC",
            tuple(symbols),
        )
    )
