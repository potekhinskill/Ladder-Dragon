# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate dynamic SQLite schema fragments before interpolation.
"""Small fail-closed helpers for unavoidable SQLite identifier interpolation."""

from __future__ import annotations

import re


SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SQLITE_COLUMN_DDL_RE = re.compile(
    r"^(?:TEXT|REAL|INTEGER)"
    r"(?: NOT NULL)?"
    r"(?: DEFAULT (?:-?[0-9]+(?:\.[0-9]+)?|'[^']*'))?$"
)


def quote_sqlite_identifier(value: str) -> str:
    """Validate and quote one SQLite table, view, or column identifier."""
    if not isinstance(value, str) or not SQLITE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError("invalid SQLite identifier")
    return f'"{value}"'


def validate_sqlite_column_ddl(value: str) -> str:
    """Allow only the narrow column declarations used by schema migrations."""
    if not isinstance(value, str) or not SQLITE_COLUMN_DDL_RE.fullmatch(value):
        raise ValueError("invalid SQLite column declaration")
    return value
