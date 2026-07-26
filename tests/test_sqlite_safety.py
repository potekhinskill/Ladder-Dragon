# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: ensure dynamic SQLite schema identifiers fail closed.
"""Tests for strict SQLite identifier and migration-fragment validation."""

from __future__ import annotations

import sqlite3

import pytest

from bin import pnl_24h
from ladder_dragon.execution import tools_stats
from ladder_dragon.sqlite_safety import (
    quote_sqlite_identifier,
    validate_sqlite_column_ddl,
)


def test_sqlite_identifiers_are_validated_and_quoted():
    assert quote_sqlite_identifier("trades_exact") == '"trades_exact"'
    for invalid in (
        "",
        "trades;DROP TABLE trades",
        "table-name",
        "1table",
        'trades"',
    ):
        with pytest.raises(ValueError, match="identifier"):
            quote_sqlite_identifier(invalid)


def test_sqlite_column_declarations_use_a_narrow_grammar():
    assert validate_sqlite_column_ddl(
        "TEXT NOT NULL DEFAULT 'ATTRIBUTION'"
    ) == "TEXT NOT NULL DEFAULT 'ATTRIBUTION'"
    assert validate_sqlite_column_ddl("REAL NOT NULL DEFAULT 0") == (
        "REAL NOT NULL DEFAULT 0"
    )
    for invalid in (
        "TEXT; DROP TABLE ai_decisions",
        "BLOB",
        "TEXT DEFAULT CURRENT_TIMESTAMP",
    ):
        with pytest.raises(ValueError, match="column declaration"):
            validate_sqlite_column_ddl(invalid)


def test_sql_identifier_consumers_reject_injected_names():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE trades(ts INTEGER)")

    with pytest.raises(ValueError):
        pnl_24h.detect_ts_div(connection, "ts); DROP TABLE trades;--")
    with pytest.raises(ValueError):
        tools_stats._table_columns(
            connection,
            "trades); DROP TABLE trades;--",
        )
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name='trades'"
    ).fetchone() == ("trades",)
