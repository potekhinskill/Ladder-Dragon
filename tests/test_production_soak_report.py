from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from bin.production_soak_report import build_report
from ladder_dragon.execution.order_recovery import OrderJournal


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
