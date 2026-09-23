from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from ladder_dragon.persistence import prediction_connection as policy
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


def test_wal_backup_snapshot_allows_durable_prediction_writer(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    with closing(store._connect()) as writer, writer:
        assert writer.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert writer.execute("PRAGMA synchronous").fetchone() == (2,)
        assert writer.execute("PRAGMA busy_timeout").fetchone() == (10000,)
        assert writer.execute("PRAGMA wal_autocheckpoint").fetchone() == (1000,)
        writer.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        writer.execute("INSERT INTO probe VALUES (1)")
    with closing(sqlite3.connect(f"file:{store.path}?mode=ro", uri=True)) as source:
        source.execute("PRAGMA query_only=ON")
        source.execute("BEGIN")
        assert source.execute("SELECT * FROM probe").fetchall() == [(1,)]
        calls = []

        def concurrent_write(*_):
            if calls:
                return
            calls.append(True)
            with closing(store._connect()) as writer, writer:
                # Prove success without using the production ten-second wait.
                writer.execute("PRAGMA busy_timeout=0")
                writer.execute("INSERT INTO probe VALUES (2)")

        with closing(sqlite3.connect(tmp_path / "copy.sqlite3")) as target:
            source.backup(target, progress=concurrent_write)
            assert calls == [True]
            assert target.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert target.execute("SELECT * FROM probe").fetchall() == [(1,)]
        assert source.execute("SELECT * FROM probe").fetchall() == [(1,)]
        with pytest.raises(sqlite3.OperationalError):
            source.execute("INSERT INTO probe VALUES (3)")
    with closing(store._connect()) as reopened:
        assert reopened.execute("SELECT * FROM probe").fetchall() == [(1,), (2,)]


def test_wal_keeps_competing_writers_fail_closed(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    with closing(store._connect()) as owner, closing(store._connect()) as contender:
        owner.execute("BEGIN IMMEDIATE")
        contender.execute("PRAGMA busy_timeout=0")
        with pytest.raises(sqlite3.OperationalError):
            contender.execute("BEGIN IMMEDIATE")
        owner.rollback()
        contender.execute("BEGIN IMMEDIATE")
        contender.rollback()


def test_backup_includes_committed_wal_but_not_pending_transaction(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    target_path = tmp_path / "backup.sqlite3"
    with closing(store._connect()) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        writer.execute("INSERT INTO probe VALUES (1)")
        writer.commit()
        assert Path(str(store.path) + "-wal").stat().st_size > 0
        writer.execute("INSERT INTO probe VALUES (2)")
        with closing(sqlite3.connect(f"file:{store.path}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(target_path)) as target:
                source.backup(target)
        writer.rollback()
    with closing(sqlite3.connect(target_path)) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert restored.execute("SELECT * FROM probe").fetchall() == [(1,)]


def test_existing_delete_database_keeps_committed_rows(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE probe (id INTEGER)")
        connection.execute("INSERT INTO probe VALUES (1)")
    store = PredictionShadowStore(path)
    with closing(store._connect()) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("SELECT * FROM probe").fetchall() == [(1,)]


def test_wal_transition_blocked_by_reader_preserves_database(tmp_path, monkeypatch):
    path = tmp_path / "locked.sqlite3"
    connect = sqlite3.connect
    with closing(connect(path)) as owner:
        owner.execute("CREATE TABLE probe (id INTEGER)")
        owner.execute("INSERT INTO probe VALUES (1)")
        owner.commit()
        owner.execute("BEGIN")
        owner.execute("SELECT * FROM probe").fetchall()
        monkeypatch.setattr(policy.sqlite3, "connect", lambda path, **kw: connect(path, timeout=0))
        with pytest.raises(sqlite3.OperationalError):
            PredictionShadowStore(path)
        assert owner.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert owner.execute("SELECT * FROM probe").fetchall() == [(1,)]
    with closing(connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='prediction_decisions'").fetchone() == (0,)


def test_connection_rejects_unexpected_delete_mode(tmp_path):
    path = tmp_path / "unexpected.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE probe (id INTEGER)")
    with pytest.raises(sqlite3.OperationalError, match="mode changed"):
        policy.connect_prediction_database(path)


def test_unsupported_wal_mode_is_not_silently_accepted():
    with pytest.raises(sqlite3.OperationalError, match="WAL mode unavailable"):
        policy.prepare_prediction_database(":memory:")


def test_wal_reader_service_sandbox_allows_sidecar_coordination():
    root = Path(__file__).resolve().parents[1]
    unit = (root / "deploy/ladder-dragon-database-retention.service").read_text()
    assert "ReadWritePaths=/home/bot/apps/binance_bot/db " in unit
    backup = (root / "deploy/backup_raspberry_pi.sh").read_text()
    assert 'sqlite3.connect(f"file:{source}?mode=ro", uri=True' in backup
    assert "src.backup(out)" in backup
