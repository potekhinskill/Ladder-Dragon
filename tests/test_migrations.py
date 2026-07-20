from pathlib import Path
import sqlite3

from bin.db_migrate import migrate


def test_migrations_are_repeatable(tmp_path: Path):
    db = tmp_path / "bot.db"
    assert migrate(str(db)) == ["001", "002", "003", "004", "005", "006"]
    assert migrate(str(db)) == []
    with sqlite3.connect(db) as con:
        versions = [row[0] for row in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == ["001", "002", "003", "004", "005", "006"]
        assert con.execute(
            "SELECT completed FROM database_bootstrap "
            "WHERE target_storage='exact-accounting'"
        ).fetchone() == (1,)
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trades'").fetchone()
        trade_columns = {row[1] for row in con.execute("PRAGMA table_info(trades)")}
        inventory_columns = {row[1] for row in con.execute("PRAGMA table_info(inventory)")}
        assert {"gross_qty", "net_qty", "commission_asset", "commission_quote"} <= trade_columns
        assert {"qty_text", "avg_cost_text", "realized_pnl_text"} <= inventory_columns
        assert {"price", "qty", "fee_quote"}.isdisjoint(trade_columns)
        assert {"qty", "avg_cost", "realized_pnl"}.isdisjoint(inventory_columns)
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
        views = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            )
        }
        assert {"trades_exact", "inventory_exact"} <= views

        con.execute(
            "INSERT INTO trades(symbol,side,price_text,gross_qty,net_qty,"
            "commission_asset,commission_amount,commission_quote,"
            "commission_value_status,ts) VALUES"
            "('SOLUSDT','BUY','75.125','0.125','0.125','USDT','0.01',"
            "'0.01','exact',1)"
        )
        trade = con.execute(
            "SELECT price_text,gross_qty_text,net_qty_text "
            "FROM trades_exact WHERE symbol='SOLUSDT'"
        ).fetchone()
        assert trade == ("75.125", "0.125", "0.125")

        con.execute(
            "INSERT INTO inventory(symbol,qty_text,avg_cost_text,realized_pnl_text) "
            "VALUES('SOLUSDT','1.5','76.25','0.5')"
        )
        inventory = con.execute(
            "SELECT qty_text,avg_cost_text,realized_pnl_text "
            "FROM inventory_exact WHERE symbol='SOLUSDT'"
        ).fetchone()
        assert inventory == ("1.5", "76.25", "0.5")

        triggers = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        assert not {
            "trades_exact_after_insert",
            "inventory_exact_after_insert",
            "inventory_exact_after_legacy_update",
        } & triggers


def test_interrupted_empty_exact_bootstrap_resumes(tmp_path: Path):
    database = tmp_path / "interrupted.db"
    migrate(str(database), exact_new_database=False)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE database_bootstrap("
            "target_storage TEXT PRIMARY KEY,completed INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO database_bootstrap VALUES('exact-accounting',0)"
        )

    assert migrate(str(database)) == []
    with sqlite3.connect(database) as connection:
        assert {"price", "qty", "fee_quote"}.isdisjoint(
            {row[1] for row in connection.execute("PRAGMA table_info(trades)")}
        )
        assert connection.execute(
            "SELECT completed FROM database_bootstrap"
        ).fetchone() == (1,)
