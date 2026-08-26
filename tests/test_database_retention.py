import gzip
import json
from pathlib import Path
import sqlite3
import sys

import pytest

from bin import database_retention
from ladder_dragon.persistence.retention import (
    rotate_market_scenarios,
    rotate_prediction_shadow,
)


def _database(path: Path, *, old_ms: int, fresh_ms: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE prediction_decisions(
                decision_id TEXT PRIMARY KEY, schema_version INTEGER, kind TEXT,
                symbol TEXT, snapshot_ts_ms INTEGER, feature_json TEXT,
                plan_json TEXT, baseline_plan_json TEXT, prediction_json TEXT,
                algorithm_decision TEXT, created_at_ms INTEGER
            );
            CREATE TABLE prediction_outcomes(
                decision_id TEXT, horizon_min INTEGER, eligible_at_ms INTEGER,
                resolved_at_ms INTEGER, outcome_json TEXT,
                baseline_outcome_json TEXT, terminal_reason TEXT,
                expired_at_ms INTEGER, source_sha256 TEXT,
                PRIMARY KEY(decision_id,horizon_min)
            );
            """
        )
        for decision_id, created in (("terminal", old_ms), ("pending", old_ms), ("fresh", fresh_ms)):
            connection.execute(
                "INSERT INTO prediction_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (decision_id, 1, "STRATEGY", "SOLUSDT", created, "{}", "{}", None, "[]", "test", created),
            )
        connection.execute(
            "INSERT INTO prediction_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
            ("terminal", 1, old_ms, old_ms, "{}", "{}", "RESOLVED", None, None),
        )
        connection.execute(
            "INSERT INTO prediction_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
            ("pending", 1, old_ms, None, None, None, None, None, None),
        )
        connection.execute(
            "INSERT INTO prediction_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
            ("fresh", 1, fresh_ms, fresh_ms, "{}", "{}", "RESOLVED", None, None),
        )


def _backup(path: Path, now: float) -> None:
    stamp = __import__("datetime").datetime.fromtimestamp(
        now - 60, tz=__import__("datetime").timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S UTC")
    path.write_text(json.dumps({"status": "success", "updated_at": stamp}))


def test_retention_archives_terminal_rows_and_preserves_pending_and_fresh(tmp_path):
    now = 2_000_000_000.0
    cutoff_ms = int((now - 365 * 86_400) * 1000)
    database = tmp_path / "prediction.sqlite3"
    backup = tmp_path / "backup.json"
    _database(database, old_ms=cutoff_ms - 1000, fresh_ms=cutoff_ms + 1000)
    _backup(backup, now)

    result = rotate_prediction_shadow(
        database, tmp_path / "archives", backup, now=now
    )

    assert result["status"] == "PASS"
    assert result["deleted_decisions"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT decision_id FROM prediction_decisions ORDER BY decision_id"
        ).fetchall() == [("fresh",), ("pending",)]
    archive = tmp_path / "archives" / str(result["archive"])
    with gzip.open(archive, "rt", encoding="utf-8") as stream:
        payload = json.loads(stream.readline())
    assert payload["decision"]["decision_id"] == "terminal"
    assert payload["outcomes"][0]["terminal_reason"] == "RESOLVED"


def test_retention_blocks_without_fresh_encrypted_backup(tmp_path):
    now = 2_000_000_000.0
    database = tmp_path / "prediction.sqlite3"
    old_ms = int((now - 400 * 86_400) * 1000)
    _database(database, old_ms=old_ms, fresh_ms=int(now * 1000))

    result = rotate_prediction_shadow(
        database, tmp_path / "archives", tmp_path / "missing.json", now=now
    )

    assert result["status"] == "BLOCKED"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM prediction_decisions"
        ).fetchone()[0] == 3
    assert not (tmp_path / "archives").exists()


def test_retention_empty_run_is_successful_with_fresh_backup(tmp_path):
    now = 2_000_000_000.0
    database = tmp_path / "prediction.sqlite3"
    backup = tmp_path / "backup.json"
    fresh_ms = int(now * 1_000)
    _database(database, old_ms=fresh_ms, fresh_ms=fresh_ms)
    _backup(backup, now)

    result = rotate_prediction_shadow(
        database, tmp_path / "archives", backup, now=now
    )

    assert result["status"] == "PASS"
    assert result["reason"] == "no terminal prediction rows exceed retention"


def test_retention_preserves_classified_lifecycle_evidence(tmp_path):
    now = 2_000_000_000.0
    database = tmp_path / "prediction.sqlite3"
    backup = tmp_path / "backup.json"
    old_ms = int((now - 400 * 86_400) * 1000)
    _database(database, old_ms=old_ms, fresh_ms=int(now * 1000))
    _backup(backup, now)
    from ladder_dragon.strategy.prediction import PredictionShadowStore
    PredictionShadowStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE prediction_decisions SET evidence_role='CONFIRMATION' "
            "WHERE decision_id='terminal'"
        )

    result = rotate_prediction_shadow(
        database, tmp_path / "archives", backup, now=now
    )

    assert result["status"] == "PASS"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM prediction_decisions WHERE decision_id='terminal'"
        ).fetchone()[0] == 1


def test_retention_preserves_entry_diagnostic_progress_and_summaries(tmp_path):
    now = 2_000_000_000.0
    database = tmp_path / "prediction.sqlite3"
    backup = tmp_path / "backup.json"
    old_ms = int((now - 400 * 86_400) * 1000)
    _database(database, old_ms=old_ms, fresh_ms=int(now * 1000))
    _backup(backup, now)
    from ladder_dragon.strategy.prediction import PredictionShadowStore
    PredictionShadowStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO prediction_entry_diagnostic_progress
               VALUES(?,?,?,?,?,?,?,?)""",
            ("active", "SOLUSDT", "v22", "a" * 64, old_ms, "{}", "b" * 64, old_ms),
        )
        connection.execute(
            """INSERT INTO prediction_entry_diagnostic_summaries
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "summary", "SOLUSDT", "v22", "a" * 64, old_ms, old_ms,
                "COMPLETE", "{}", "b" * 64, old_ms,
            ),
        )

    result = rotate_prediction_shadow(
        database, tmp_path / "archives", backup, now=now
    )

    assert result["entry_diagnostics"]["summary_rows"] == 1
    assert result["entry_diagnostics"]["active_progress_rows"] == 1
    assert result["entry_diagnostics"]["retention_period"] == "indefinite"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT episode_id FROM prediction_entry_diagnostic_progress"
        ).fetchall() == [("active",)]
        assert connection.execute(
            "SELECT episode_id FROM prediction_entry_diagnostic_summaries"
        ).fetchall() == [("summary",)]


def test_market_scenario_retention_archives_only_resolved_evidence(tmp_path):
    now = 2_000_000_000.0
    old_ms = int((now - 400 * 86_400) * 1000)
    database = tmp_path / "market.sqlite3"
    backup = tmp_path / "backup.json"
    _backup(backup, now)
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE market_scenario_snapshots(
                sequence INTEGER PRIMARY KEY, snapshot_id TEXT UNIQUE,
                symbol TEXT,timeframe TEXT,as_of_open_ms INTEGER,
                as_of_close_ms INTEGER,created_at_ms INTEGER,
                entry_price_text TEXT,shadow_action TEXT,analysis_json TEXT,
                mode TEXT,apply_allowed INTEGER
            );
            CREATE TABLE market_scenario_outcomes(
                snapshot_id TEXT PRIMARY KEY,resolved_at_ms INTEGER,
                outcome_open_ms INTEGER,outcome_close_ms INTEGER,
                exit_price_text TEXT,candidate_net_return_text TEXT,
                baseline_net_return_text TEXT,edge_text TEXT
            );
            """
        )
        for sequence, identity in ((1, "resolved"), (2, "pending")):
            connection.execute(
                "INSERT INTO market_scenario_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (sequence, identity, "SOLUSDT", "1h", old_ms, old_ms, old_ms,
                 "100", "LONG", "{}", "SHADOW", 0),
            )
        connection.execute(
            "INSERT INTO market_scenario_outcomes VALUES(?,?,?,?,?,?,?,?)",
            ("resolved", old_ms, old_ms, old_ms, "101", "0.01", "0.01", "0"),
        )
    result = rotate_market_scenarios(
        database, tmp_path / "archives", backup, now=now
    )
    assert result["status"] == "PASS"
    assert result["deleted_snapshots"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT snapshot_id FROM market_scenario_snapshots"
        ).fetchall() == [("pending",)]
    with gzip.open(
        tmp_path / "archives" / str(result["archive"]), "rt", encoding="utf-8"
    ) as stream:
        assert json.loads(stream.readline())["evidence"]["snapshot_id"] == "resolved"


@pytest.mark.parametrize(("status", "expected"), (("PASS", 0), ("BLOCKED", 2)))
def test_retention_cli_exposes_blocked_status_to_systemd(
    tmp_path, monkeypatch, status, expected,
):
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        database_retention,
        "rotate_prediction_shadow",
        lambda *_args, **_kwargs: {"status": status},
    )
    monkeypatch.setattr(
        database_retention,
        "rotate_market_scenarios",
        lambda *_args, **_kwargs: {"status": status},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "database_retention",
            "--prediction-db", str(tmp_path / "prediction.sqlite3"),
            "--market-analysis-db", str(tmp_path / "market.sqlite3"),
            "--stats-db", str(tmp_path / "stats.sqlite3"),
            "--order-journal", str(tmp_path / "journal.sqlite3"),
            "--ai-db", str(tmp_path / "ai.sqlite3"),
            "--archive-dir", str(tmp_path / "archives"),
            "--backup-status", str(tmp_path / "backup.json"),
            "--report", str(report),
        ],
    )

    assert database_retention.main() == expected
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == status


def test_retention_rejects_short_or_unbounded_policy(tmp_path):
    for value in (0, 29, 3651):
        try:
            rotate_prediction_shadow(
                tmp_path / "db", tmp_path / "archive", tmp_path / "backup",
                retention_days=value,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe retention value was accepted")
