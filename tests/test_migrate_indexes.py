import sqlite3

import pytest

from bin.migrate_indexes import index_statements


def _connection(columns: str) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(f"CREATE TABLE trades({columns})")
    return connection


def test_exact_accounting_schema_uses_exact_covering_columns():
    connection = _connection(
        "symbol TEXT, ts INTEGER, side TEXT, price_text TEXT, gross_qty TEXT, "
        "commission_quote TEXT, trade_id INTEGER"
    )
    statements = index_statements(connection)
    assert "price_text, gross_qty, commission_quote" in statements[0]
    connection.execute(statements[0])
    columns = [
        row[2]
        for row in connection.execute("PRAGMA index_info(trades_monthly_cover)")
    ]
    assert columns == [
        "symbol",
        "ts",
        "side",
        "price_text",
        "gross_qty",
        "commission_quote",
    ]


def test_legacy_accounting_schema_remains_supported():
    connection = _connection(
        "symbol TEXT, ts INTEGER, side TEXT, price REAL, qty REAL, "
        "fee_quote REAL, trade_id INTEGER"
    )
    assert "price, qty, fee_quote" in index_statements(connection)[0]


def test_unknown_accounting_schema_fails_closed():
    connection = _connection("symbol TEXT, ts INTEGER, trade_id INTEGER")
    with pytest.raises(RuntimeError, match="cannot support"):
        index_statements(connection)
