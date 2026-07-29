# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: execute SQLite scripts without the implicit commits of executescript.
"""Parse and execute SQLite scripts inside a caller-owned transaction."""

from __future__ import annotations

import re
import sqlite3

from ladder_dragon.sqlite_safety import (
    quote_sqlite_identifier,
    validate_sqlite_column_ddl,
)


_TRANSACTION_CONTROL = re.compile(
    r"^\s*(?:(?:--[^\n]*\n)|(?:/\*.*?\*/\s*))*"
    r"(?:BEGIN|COMMIT|END\s+TRANSACTION|ROLLBACK)\b",
    re.IGNORECASE | re.DOTALL,
)
_ADD_COLUMN = re.compile(
    r"^\s*ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
    r"ADD\s+COLUMN\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)\s*;\s*$",
    re.IGNORECASE | re.DOTALL,
)


def parse_sql_statements(script: str) -> tuple[str, ...]:
    """Return complete SQLite statements while preserving trigger bodies."""
    statements: list[str] = []
    pending: list[str] = []
    for line in script.splitlines(keepends=True):
        pending.append(line)
        candidate = "".join(pending)
        if sqlite3.complete_statement(candidate):
            statement = candidate.strip()
            if statement:
                if _TRANSACTION_CONTROL.match(statement):
                    raise ValueError(
                        "migration scripts must not control transactions"
                    )
                statements.append(statement)
            pending.clear()
    if "".join(pending).strip():
        raise ValueError("migration script ends with an incomplete SQL statement")
    return tuple(statements)


def _column_contract(definition: str) -> tuple[str, bool, str | None]:
    definition = " ".join(definition.split())
    validate_sqlite_column_ddl(definition)
    tokens = definition.split()
    column_type = tokens[0].upper()
    not_null = " NOT NULL" in f" {definition.upper()}"
    default_match = re.search(r"\sDEFAULT\s+(.+)$", definition, re.IGNORECASE)
    default = default_match.group(1) if default_match else None
    return column_type, not_null, default


def _existing_column(
    connection: sqlite3.Connection, table: str, column: str
) -> tuple[str, bool, str | None] | None:
    safe_table = quote_sqlite_identifier(table)
    for row in connection.execute(f"PRAGMA table_info({safe_table})"):
        if str(row[1]) == column:
            return str(row[2]).upper(), bool(row[3]), (
                None if row[4] is None else str(row[4])
            )
    return None


def execute_sql_script(
    connection: sqlite3.Connection,
    script: str,
    *,
    guard_existing_columns: bool = False,
) -> None:
    """Execute a script without committing the caller-owned transaction."""
    for statement in parse_sql_statements(script):
        add_column = _ADD_COLUMN.match(statement) if guard_existing_columns else None
        if add_column:
            table, column, definition = add_column.groups()
            expected = _column_contract(definition)
            existing = _existing_column(connection, table, column)
            if existing is not None:
                if existing != expected:
                    raise RuntimeError(
                        f"existing column contract differs: {table}.{column}"
                    )
                continue
        connection.execute(statement)
