from pathlib import Path
import hashlib
import sqlite3

import pytest

import ladder_dragon.persistence.migrations as migration_runner
from ladder_dragon.persistence.migrations import MIGRATIONS, migrate
from ladder_dragon.execution.inventory_lots import sync_exchange_fill


def test_migrations_are_repeatable(tmp_path: Path):
    db = tmp_path / "bot.db"
    assert migrate(str(db)) == [
        "001", "002", "003", "004", "005", "006", "007", "008"
    ]
    assert migrate(str(db)) == []
    with sqlite3.connect(db) as con:
        versions = [row[0] for row in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == [
            "001", "002", "003", "004", "005", "006", "007", "008"
        ]
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
            "unmanaged_dust_qty", "history_reset_trade_id",
            "stats_trade_max_id", "cursor_gap_start_trade_id",
            "cursor_gap_end_trade_id", "status",
        } <= import_columns
        consumption_columns = {
            row[1] for row in con.execute(
                "PRAGMA table_info(inventory_lot_consumptions)"
            )
        }
        assert {
            "symbol", "source_trade_id", "source_order_id", "qty", "price",
            "executed_at", "recorded_at",
        } <= consumption_columns
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


def test_failed_migration_rolls_back_schema_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_atomic.sql").write_text(
        "CREATE TABLE partial_change(id INTEGER);\n"
        "CREATE TABLE broken(\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS", migration_dir)
    database = tmp_path / "atomic.db"

    with pytest.raises(ValueError, match="incomplete SQL statement"):
        migrate(str(database), exact_new_database=False)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='partial_change'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall() == []


def test_migration_version_record_failure_rolls_back_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_atomic.sql").write_text(
        "CREATE TABLE atomic_change(id INTEGER);\n"
        "CREATE TRIGGER reject_migration_record "
        "BEFORE INSERT ON schema_migrations "
        "BEGIN SELECT RAISE(ABORT, 'reject version record'); END;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS", migration_dir)
    database = tmp_path / "version-record.db"

    with pytest.raises(sqlite3.IntegrityError, match="reject version record"):
        migrate(str(database), exact_new_database=False)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='atomic_change'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='reject_migration_record'"
        ).fetchone() is None


def test_duplicate_migration_versions_fail_before_database_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_first.sql").write_text(
        "CREATE TABLE first_change(id INTEGER);\n", encoding="utf-8"
    )
    (migration_dir / "001_second.sql").write_text(
        "CREATE TABLE second_change(id INTEGER);\n", encoding="utf-8"
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS", migration_dir)
    database = tmp_path / "duplicate.db"

    with pytest.raises(RuntimeError, match="duplicate migration version"):
        migrate(str(database), exact_new_database=False)

    assert not database.exists()


def test_partial_legacy_add_column_migration_resumes_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_resume.sql").write_text(
        "ALTER TABLE records ADD COLUMN exact_text TEXT;\n"
        "ALTER TABLE records ADD COLUMN source_id INTEGER NOT NULL DEFAULT 0;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS", migration_dir)
    database = tmp_path / "partial.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records(id INTEGER)")
        connection.execute("ALTER TABLE records ADD COLUMN exact_text TEXT")

    assert migrate(str(database), exact_new_database=False) == ["001"]

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]: (row[2], row[3], row[4])
            for row in connection.execute("PRAGMA table_info(records)")
        }
        assert columns["exact_text"] == ("TEXT", 0, None)
        assert columns["source_id"] == ("INTEGER", 1, "0")


def test_partial_migration_rejects_mismatched_existing_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_resume.sql").write_text(
        "ALTER TABLE records ADD COLUMN exact_text TEXT;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS", migration_dir)
    database = tmp_path / "partial-mismatch.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records(id INTEGER, exact_text INTEGER)")

    with pytest.raises(RuntimeError, match="column contract differs"):
        migrate(str(database), exact_new_database=False)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall() == []


def test_exact_bootstrap_and_completion_marker_roll_back_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    database = tmp_path / "bootstrap-atomic.db"
    migrate(str(database), exact_new_database=False)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE database_bootstrap("
            "target_storage TEXT PRIMARY KEY,completed INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO database_bootstrap VALUES('exact-accounting',0)"
        )

    def fail_after_schema_write(connection: sqlite3.Connection) -> bool:
        connection.execute("CREATE TABLE leaked_bootstrap_state(id INTEGER)")
        raise RuntimeError("injected bootstrap failure")

    monkeypatch.setattr(
        "ladder_dragon.execution.accounting_retirement."
        "bootstrap_exact_accounting_connection",
        fail_after_schema_write,
    )

    with pytest.raises(RuntimeError, match="injected bootstrap failure"):
        migrate(str(database))

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT completed FROM database_bootstrap"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='leaked_bootstrap_state'"
        ).fetchone() is None


def test_fifo_sell_migration_seeds_existing_valued_trades(tmp_path: Path):
    database = tmp_path / "upgrade-from-006.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations("
            "version TEXT PRIMARY KEY,checksum TEXT NOT NULL,"
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        for migration in sorted(MIGRATIONS.glob("[0-9][0-9][0-6]_*.sql")):
            sql = migration.read_text(encoding="utf-8")
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES(?,?)",
                (
                    migration.name.split("_", 1)[0],
                    hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                ),
            )
        connection.execute(
            "INSERT INTO trades("
            "symbol,side,price,qty,fee_quote,ts,trade_id,price_text,"
            "gross_qty,net_qty,commission_asset,commission_amount,"
            "commission_quote,commission_value_status"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "SOLUSDT", "SELL", 110.0, 0.5, 0.05, 1_700_000_001_000,
                21, "110", "0.5", "0.5", "USDT", "0.05", "0.05", "exact",
            ),
        )

    assert migrate(str(database), exact_new_database=False) == ["007", "008"]
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT symbol,source_trade_id,source_order_id,qty,price "
            "FROM inventory_lot_consumptions"
        ).fetchone() == ("SOLUSDT", "21", "", "0.5", "110")
        repeated = sync_exchange_fill(
            connection,
            {
                "symbol": "SOLUSDT",
                "side": "SELL",
                "price": "110",
                "qty": "0.5",
                "fee_quote": "0.05",
                "commission_asset": "USDT",
                "commission_amount": "0.05",
                "trade_id": 21,
                "order_id": 11,
                "ts": 1_700_000_001_000,
            },
        )
        assert repeated == []
        assert connection.execute(
            "SELECT source_order_id FROM inventory_lot_consumptions "
            "WHERE symbol='SOLUSDT' AND source_trade_id='21'"
        ).fetchone() == ("11",)
