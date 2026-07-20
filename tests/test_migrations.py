from pathlib import Path
import sqlite3

from bin.db_migrate import migrate


def test_migrations_are_repeatable(tmp_path: Path):
    db = tmp_path / "bot.db"
    assert migrate(str(db)) == ["001", "002", "003", "004", "005"]
    assert migrate(str(db)) == []
    with sqlite3.connect(db) as con:
        versions = [row[0] for row in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == ["001", "002", "003", "004", "005"]
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trades'").fetchone()
        trade_columns = {row[1] for row in con.execute("PRAGMA table_info(trades)")}
        inventory_columns = {row[1] for row in con.execute("PRAGMA table_info(inventory)")}
        assert {"gross_qty", "net_qty", "commission_asset", "commission_quote"} <= trade_columns
        assert {"qty_text", "avg_cost_text", "realized_pnl_text"} <= inventory_columns
        import_columns = {
            row[1] for row in con.execute(
                "PRAGMA table_info(inventory_lot_imports)"
            )
        }
        assert {
            "batch_id", "plan_sha256", "history_sha256", "weighted_average",
            "last_trade_id", "baseline_realized_pnl", "prehistory_qty",
            "unmanaged_dust_qty", "history_reset_trade_id", "status",
        } <= import_columns
