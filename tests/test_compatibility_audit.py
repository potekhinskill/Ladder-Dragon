from pathlib import Path
import sqlite3

from bin.db_migrate import migrate
from ladder_dragon.execution.compatibility_audit import audit_compatibility


def test_compatibility_audit_accepts_exact_database_without_legacy_paths(tmp_path):
    database = tmp_path / "stats.db"
    migrate(str(database), exact_new_database=False)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO trades(symbol,side,price,qty,fee_quote,ts,"
            "price_text,gross_qty,net_qty,commission_value_status) "
            "VALUES('SOLUSDT','BUY',75.1,0.1,0,1,'75.1','0.1','0.1','quote')"
        )
        connection.execute(
            "INSERT INTO inventory(symbol,qty,avg_cost,realized_pnl,"
            "qty_text,avg_cost_text,realized_pnl_text) "
            "VALUES('SOLUSDT',0.1,75.1,0,'0.1','75.1','0')"
        )

    report = audit_compatibility(database)

    assert report.ready_for_major_removal is True
    assert report.reasons == ()
    assert report.legacy_commission_rows == 0
    assert report.legacy_trade_real_columns == ("fee_quote", "price", "qty")
    assert report.legacy_inventory_real_columns == (
        "avg_cost", "qty", "realized_pnl",
    )
    assert report.as_dict()["sqlite_retirement_required"] is True


def test_compatibility_audit_blocks_legacy_commission_provenance(tmp_path):
    database = tmp_path / "stats.db"
    migrate(str(database), exact_new_database=False)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO trades(symbol,side,price,qty,fee_quote,ts,"
            "price_text,gross_qty,net_qty,commission_value_status) "
            "VALUES('SOLUSDT','BUY',75.1,0.1,0,1,'75.1','0.1','0.1','legacy')"
        )

    report = audit_compatibility(database)

    assert report.ready_for_major_removal is False
    assert report.legacy_commission_rows == 1
    assert "legacy or unpriced commissions" in " ".join(report.reasons)


def test_compatibility_audit_fails_closed_for_legacy_path_and_old_schema(tmp_path):
    database = tmp_path / "old.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE trades(id INTEGER PRIMARY KEY, symbol TEXT)"
        )
        connection.execute(
            "CREATE TABLE inventory(symbol TEXT PRIMARY KEY, qty REAL)"
        )
    legacy = tmp_path / "bot-alerts.env"
    legacy.write_text("BOT_TOKEN=redacted\n")

    report = audit_compatibility(database, legacy_paths=(legacy,))

    assert report.ready_for_major_removal is False
    assert str(legacy) in report.legacy_paths
    assert "trades exact-text schema is incomplete" in report.reasons
