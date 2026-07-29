from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from bin import production_soak_report
from bin.production_soak_report import build_report, notify_on_transition
from ladder_dragon.execution.order_recovery import OrderJournal


def _prediction_database(
    path: Path,
    rows: list[tuple[int, int | None, str | None, str | None]],
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE prediction_outcomes (
               eligible_at_ms INTEGER NOT NULL,
               outcome_json TEXT,
               resolved_at_ms INTEGER,
               terminal_reason TEXT,
               expired_at_ms INTEGER)"""
        )
        connection.executemany(
            """INSERT INTO prediction_outcomes
               (eligible_at_ms,resolved_at_ms,terminal_reason,outcome_json)
               VALUES (?,?,?,?)""",
            rows,
        )


def test_soak_report_cannot_approve_short_or_incomplete_run(tmp_path):
    now = datetime(2026, 7, 23, 6, tzinfo=timezone.utc).timestamp()
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({
        "state": "RUNNING",
        "execution_mode": "LIVE",
        "venue": "mainnet",
        "started_at": datetime.fromtimestamp(
            now - 3600, timezone.utc
        ).isoformat(),
        "updated_at": datetime.fromtimestamp(
            now - 5, timezone.utc
        ).isoformat(),
    }))
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    prediction = tmp_path / "prediction.sqlite3"
    with sqlite3.connect(prediction) as connection:
        connection.execute(
            """CREATE TABLE prediction_outcomes (
               outcome_json TEXT,resolved_at_ms INTEGER,
               terminal_reason TEXT)"""
        )

    report = build_report(
        runtime_path=runtime,
        journal_path=journal.path,
        prediction_path=prediction,
        required_hours=24,
        required_lifecycles=3,
        required_predictions=100,
        now_epoch=now,
    )

    assert report["approved"] is False
    assert report["checks"]["duration_met"] is False
    assert report["checks"]["exact_lifecycles_met"] is False
    assert report["checks"]["prediction_samples_met"] is False
    assert report["checks"]["prediction_gate_approved"] is False


def test_continuous_shadow_future_pending_is_not_a_backlog(tmp_path):
    now = datetime(2026, 7, 23, 6, tzinfo=timezone.utc).timestamp()
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({
        "state": "RUNNING",
        "execution_mode": "LIVE",
        "venue": "mainnet",
        "started_at": datetime.fromtimestamp(
            now - 25 * 3600, timezone.utc
        ).isoformat(),
        "updated_at": datetime.fromtimestamp(
            now - 5, timezone.utc
        ).isoformat(),
        "prediction": {
            "symbols": {"SOLUSDT": {"gate": {"approved": True}}}
        },
    }))
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    prediction = tmp_path / "prediction.sqlite3"
    now_ms = int(now * 1000)
    _prediction_database(
        prediction,
        [
            (now_ms + 60_000, None, None, None),
            (now_ms + 300_000, None, None, None),
            (now_ms + 900_000, None, None, None),
            (now_ms - 60_000, None, None, None),
            (
                now_ms - 26 * 3600 * 1000,
                now_ms - 26 * 3600 * 1000,
                "INSUFFICIENT_HISTORY",
                None,
            ),
        ],
    )

    report = build_report(
        runtime_path=runtime,
        journal_path=journal.path,
        prediction_path=prediction,
        required_hours=24,
        required_lifecycles=3,
        required_predictions=100,
        maximum_settlement_delay_sec=300,
        now_epoch=now,
    )

    assert report["prediction"]["pending"] == 4
    assert report["prediction"]["pending_future"] == 3
    assert report["prediction"]["pending_settling"] == 1
    assert report["prediction"]["overdue"] == 0
    assert report["prediction"]["expired"] == 0
    assert report["prediction"]["expired_total"] == 1
    assert report["checks"]["no_prediction_backlog"] is True


def test_overdue_or_expired_shadow_outcome_blocks_soak(tmp_path):
    now = datetime(2026, 7, 23, 6, tzinfo=timezone.utc).timestamp()
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({
        "state": "RUNNING",
        "execution_mode": "LIVE",
        "venue": "mainnet",
        "started_at": datetime.fromtimestamp(
            now - 25 * 3600, timezone.utc
        ).isoformat(),
        "updated_at": datetime.fromtimestamp(
            now - 5, timezone.utc
        ).isoformat(),
    }))
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    prediction = tmp_path / "prediction.sqlite3"
    now_ms = int(now * 1000)
    _prediction_database(
        prediction,
        [
            (now_ms - 301_000, None, None, None),
            (
                now_ms - 900_000,
                now_ms - 800_000,
                "INSUFFICIENT_HISTORY",
                None,
            ),
        ],
    )

    report = build_report(
        runtime_path=runtime,
        journal_path=journal.path,
        prediction_path=prediction,
        required_hours=24,
        required_lifecycles=3,
        required_predictions=100,
        maximum_settlement_delay_sec=300,
        now_epoch=now,
    )

    assert report["prediction"]["overdue"] == 1
    assert report["prediction"]["expired"] == 1
    assert report["prediction"]["expired_total"] == 1
    assert report["checks"]["no_prediction_backlog"] is False


def test_soak_report_missing_runtime_fails_closed(tmp_path):
    report = build_report(
        runtime_path=tmp_path / "missing-runtime.json",
        journal_path=tmp_path / "missing-journal.sqlite3",
        prediction_path=tmp_path / "missing-prediction.sqlite3",
        required_hours=24,
        required_lifecycles=3,
        required_predictions=100,
        now_epoch=1_700_000_000,
    )
    assert report["approved"] is False
    assert report["runtime"]["state"] == "UNAVAILABLE"
    assert report["checks"]["runtime_running"] is False


def test_soak_telegram_notifies_only_on_status_transition(
    tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        production_soak_report,
        "notify",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )
    state = tmp_path / "notification-state.json"
    report = {
        "approved": False,
        "checks": {"duration_met": False, "runtime_running": True},
        "product_version": "test",
    }
    assert notify_on_transition(report, state) is True
    assert notify_on_transition(report, state) is False
    changed = dict(report)
    changed["approved"] = True
    changed["checks"] = {key: True for key in report["checks"]}
    assert notify_on_transition(changed, state) is True
    assert len(calls) == 2
