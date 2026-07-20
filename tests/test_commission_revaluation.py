from decimal import Decimal
import sqlite3

import pytest

from bin.db_migrate import migrate
from ladder_dragon.execution import tools_stats
from ladder_dragon.execution.commission_revaluation import (
    apply_revaluation,
    build_revaluation,
    legacy_rows,
)


def _legacy_database(path):
    migrate(str(path), exact_new_database=False)
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO trades(symbol,side,price,qty,fee_quote,ts,trade_id,"
        "price_text,gross_qty,net_qty,commission_value_status) VALUES"
        "('SOLUSDT','BUY',100,1,0,1700000000000,7,'100','1','1','legacy')"
    )
    connection.execute(
        "INSERT INTO inventory(symbol,qty,avg_cost,realized_pnl,qty_text,"
        "avg_cost_text,realized_pnl_text) VALUES"
        "('SOLUSDT',1,100,0,'1','100','0')"
    )
    connection.commit()
    return connection


def test_exact_exchange_fill_repairs_commission_and_net_quantity(tmp_path):
    connection = _legacy_database(tmp_path / "stats.db")
    rows = legacy_rows(connection)
    exchange = {"SOLUSDT": {7: {
        "id": 7,
        "isBuyer": True,
        "price": "100.00000000",
        "qty": "1.00000000",
        "time": 1_700_000_000_000,
        "commission": "0.001",
        "commissionAsset": "SOL",
    }}}
    result = build_revaluation(
        rows,
        exchange,
        value_commission=lambda *_args: (Decimal("0.1"), "exact"),
    )

    assert result.unresolved == ()
    assert Decimal(result.repairs[0].net_qty) == Decimal("0.999")
    assert apply_revaluation(
        connection,
        result,
        recalculate_inventory=tools_stats.recalculate_inventory,
    ) == 1
    row = connection.execute(
        "SELECT net_qty,commission_asset,commission_amount,commission_quote,"
        "commission_value_status FROM trades WHERE trade_id=7"
    ).fetchone()
    assert Decimal(row[0]) == Decimal("0.999")
    assert row[1:] == ("SOL", "0.001", "0.1", "exact")
    assert tools_stats.get_inventory_decimal(connection, "SOLUSDT")[0] == Decimal(
        "0.999"
    )
    connection.close()


def test_mismatched_fill_remains_unresolved_and_cannot_apply(tmp_path):
    connection = _legacy_database(tmp_path / "stats.db")
    result = build_revaluation(
        legacy_rows(connection),
        {"SOLUSDT": {7: {
            "id": 7,
            "isBuyer": True,
            "price": "101",
            "qty": "1",
            "time": 1_700_000_000_000,
            "commission": "0.001",
            "commissionAsset": "SOL",
        }}},
        value_commission=lambda *_args: (Decimal("0.1"), "exact"),
    )

    assert "price mismatch" in result.unresolved[0]
    with pytest.raises(RuntimeError, match="unresolved"):
        apply_revaluation(
            connection,
            result,
            recalculate_inventory=tools_stats.recalculate_inventory,
        )
    connection.close()
