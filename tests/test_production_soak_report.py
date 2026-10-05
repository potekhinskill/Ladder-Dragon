from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from ladder_dragon.verification import production_soak_command as production_soak_report
from ladder_dragon.verification.production_soak_command import build_report, notify_on_transition
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
    assert report["order_lifecycle"]["closed_exact"] is None
    assert report["order_lifecycle"]["available"] is False


@pytest.fixture
def runtime_journal(tmp_path):
    now = datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp()
    stamp = lambda seconds: datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    journal = tmp_path / "orders.sqlite3"
    payload = {
        "state": "RUNNING", "execution_mode": "LIVE", "venue": "mainnet",
        "started_at": stamp(now - 90000), "updated_at": stamp(now - 1),
        "prediction": {"symbols": {"SOLUSDT": {"gate": {"approved": True}}}},
        "order_journal": {"available": True, "source_path": str(journal),
                          "observed_at": stamp(now - 2),
                          "lifecycle": {"closed_exact": 3}},
    }
    prediction = tmp_path / "prediction.sqlite3"
    _prediction_database(prediction, [(int(now * 1000) - 1000, int(now * 1000), None, "{}")])
    return now, payload, journal, prediction


def _runtime_report(tmp_path, fixture):
    now, payload, journal, prediction = fixture
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps(payload))
    return build_report(runtime_path=runtime, journal_path=journal,
                        prediction_path=prediction, required_hours=24,
                        required_lifecycles=3, required_predictions=1,
                        journal_source="runtime", now_epoch=now)


def test_sandbox_report_uses_only_explicit_fresh_journal_snapshot(
    tmp_path, monkeypatch, runtime_journal,
):
    monkeypatch.setattr(production_soak_report, "read_order_journal_telemetry",
                        lambda *_: pytest.fail("sandbox opened live WAL journal"))
    report = _runtime_report(tmp_path, runtime_journal)
    assert report["approved"] is True
    assert report["order_lifecycle"] == {
        "available": True, "closed_exact": 3, "required": 3,
        "source": "runtime", "reason": None,
    }


@pytest.mark.parametrize("damage", [
    "missing", "unavailable", "truthy_available", "wrong_source", "missing_time",
    "stale", "future", "before_restart", "after_heartbeat", "naive", "bad_time",
    "bad_lifecycle", "missing_count", "negative", "boolean", "string", "float",
])
def test_runtime_journal_damage_blocks_without_database_fallback(
    tmp_path, monkeypatch, runtime_journal, damage,
):
    now, payload, _, _ = runtime_journal
    journal = payload["order_journal"]
    if damage == "missing":
        del payload["order_journal"]
    elif damage == "unavailable":
        journal["available"] = False
    elif damage == "truthy_available":
        journal["available"] = "true"
    elif damage == "wrong_source":
        journal["source_path"] = "/private-unrelated/orders.sqlite3"
    elif damage == "missing_time":
        del journal["observed_at"]
    elif damage in {"stale", "future", "before_restart", "after_heartbeat"}:
        offset = {"stale": -91, "future": 1, "before_restart": -90001,
                  "after_heartbeat": 0}[damage]
        journal["observed_at"] = datetime.fromtimestamp(now + offset, timezone.utc).isoformat()
    elif damage == "naive":
        journal["observed_at"] = journal["observed_at"].replace("+00:00", "")
    elif damage == "bad_time":
        journal["observed_at"] = "private-provider-text"
    elif damage == "bad_lifecycle":
        journal["lifecycle"] = []
    elif damage == "missing_count":
        journal["lifecycle"] = {}
    else:
        journal["lifecycle"]["closed_exact"] = {
            "negative": -1, "boolean": True, "string": "3", "float": 3.0,
        }[damage]
    monkeypatch.setattr(production_soak_report, "read_order_journal_telemetry",
                        lambda *_: pytest.fail("silent fallback"))
    report = _runtime_report(tmp_path, runtime_journal)
    assert report["approved"] is False
    assert report["checks"]["exact_lifecycles_met"] is False
    assert report["order_lifecycle"]["closed_exact"] is None
    assert report["order_lifecycle"]["available"] is False
    assert "private-" not in json.dumps(report)


def test_valid_journal_zero_is_distinct_from_unavailable(tmp_path, runtime_journal):
    runtime_journal[1]["order_journal"]["lifecycle"]["closed_exact"] = 0
    report = _runtime_report(tmp_path, runtime_journal)
    assert report["order_lifecycle"]["closed_exact"] == 0
    assert report["order_lifecycle"]["available"] is True
    assert report["approved"] is False


def test_direct_reader_never_falls_back_to_runtime(tmp_path, runtime_journal):
    now, payload, journal, _ = runtime_journal
    result = production_soak_report._lifecycle_evidence(payload, journal, "database", now)
    assert result["available"] is False
    assert result["closed_exact"] is None


def test_runtime_and_direct_sources_agree_on_three_real_wal_closures(tmp_path):
    from datetime import timedelta
    from ladder_dragon.supervision.journal_status import read_journal_status
    from tests.support.exchange_evidence import exit_order

    path = tmp_path / "journal.sqlite3"
    journal = OrderJournal(path, venue="mainnet")
    keeper = sqlite3.connect(path)
    try:
        assert keeper.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        started = datetime.now(timezone.utc) - timedelta(hours=25)
        for i in range(3):
            buy, oco, tp, stop = (f"{label}-{i}" for label in ("BUY", "OCO", "TP", "STOP"))
            base = 100 * (i + 1)
            journal.prepare(client_order_id=buy, symbol="SOLUSDT", side="BUY", purpose="ladder",
                            order_type="LIMIT", quantity="0.1", price="100")
            journal.record_exchange_order(buy, {"orderId": base, "status": "FILLED", "executedQty": "0.1"})
            journal.prepare(client_order_id=oco, symbol="SOLUSDT", side="SELL", purpose="oco",
                            order_type="OCO", quantity="0.1", price="102", parent_client_order_id=buy)
            journal.record_order_list(oco, {"orderListId": base + 10, "listStatusType": "EXEC_STARTED"})
            journal.record_verified_protection_legs(oco, [
                {"orderId": base + 11, "clientOrderId": tp, "type": "LIMIT_MAKER"},
                {"orderId": base + 12, "clientOrderId": stop, "type": "STOP_LOSS_LIMIT"},
            ])
            journal.mark_protected(parent_client_order_id=buy, protection_client_order_id=oco, order_list_id=base + 10)
            journal.mark_exact_lifecycle_closed(protection_client_order_id=oco, exit_order_id=base + 12,
                exit_reason="STOP", exit_order=exit_order(base + 12, stop, base + 10, "STOP_LOSS_LIMIT"))
        snapshot = read_journal_status(str(path))
        now = datetime.now(timezone.utc)
        runtime = {"started_at": started.isoformat(), "updated_at": now.isoformat(), "order_journal": snapshot}
        for source in ("database", "runtime"):
            result = production_soak_report._lifecycle_evidence(runtime, path, source, now.timestamp())
            assert result["available"] is True
            assert result["closed_exact"] == 3
        assert Path(str(path) + "-wal").exists()
    finally:
        keeper.close()


def test_publisher_adds_source_specific_timestamp_without_changing_reader(
    tmp_path, monkeypatch,
):
    from ladder_dragon.supervision import runtime as supervisor
    journal = OrderJournal(tmp_path / "journal.sqlite3", venue="mainnet")
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))
    before = datetime.now(timezone.utc)
    snapshot = supervisor._runtime_order_journal_snapshot()
    after = datetime.now(timezone.utc)
    assert snapshot["source_path"] == str(journal.path.absolute())
    assert before <= datetime.fromisoformat(snapshot["observed_at"]) <= after
    assert snapshot["lifecycle"]["closed_exact"] == 0
    assert snapshot["available"] is True


def test_cli_explicit_runtime_source(tmp_path, monkeypatch, capsys, runtime_journal):
    _, payload, journal, prediction = runtime_journal
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps(payload))
    monkeypatch.setattr(production_soak_report.time, "time", lambda: runtime_journal[0])
    assert production_soak_report.main([
        "--runtime", str(runtime), "--journal", str(journal),
        "--prediction", str(prediction), "--journal-source", "runtime",
        "--required-predictions", "1",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["order_lifecycle"]["source"] == "runtime"


@pytest.mark.parametrize("fault", ["open", "query", "close", "filesystem", "none"])
def test_prediction_storage_failure_replaces_stale_report_without_leaks(
    tmp_path, monkeypatch, capsys, runtime_journal, fault,
):
    now, payload, journal, prediction = runtime_journal
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps(payload))
    output = tmp_path / "report.json"
    output.write_text(json.dumps({"approved": True, "stale": True}))
    real_connect = sqlite3.connect
    connections, queries, closed = [], [], []
    secret_text = "private-account-secret SQL /private-path"

    class Connection:
        def __init__(self, con):
            self.con = con

        def execute(self, sql, *args):
            queries.append(sql)
            if fault == "query" and len(queries) == 3:
                raise sqlite3.OperationalError(secret_text)
            return self.con.execute(sql, *args)

        def close(self):
            self.con.close()
            closed.append(True)
            if fault == "close":
                raise OSError(secret_text)

    def connect(database, **kwargs):
        connections.append(database)
        assert database.endswith("?mode=ro")
        assert kwargs == {"uri": True, "timeout": 2}
        if fault == "open":
            raise sqlite3.OperationalError(secret_text)
        if fault == "filesystem":
            raise PermissionError(secret_text)
        return Connection(real_connect(database, **kwargs))

    monkeypatch.setattr(production_soak_report.time, "time", lambda: now)
    monkeypatch.setattr(production_soak_report.sqlite3, "connect", connect)
    rc = production_soak_report.main([
        "--runtime", str(runtime), "--journal", str(journal),
        "--prediction", str(prediction), "--journal-source", "runtime",
        "--required-predictions", "1", "--output", str(output),
    ])
    report = json.loads(output.read_text())
    assert json.loads(capsys.readouterr().out) == report
    assert "stale" not in report
    assert report["generated_at"] == datetime.fromtimestamp(now, timezone.utc).isoformat()
    assert len(connections) == 1  # No retry or alternative source after uncertainty.
    assert closed == ([] if fault in {"open", "filesystem"} else [True])
    assert "private-" not in json.dumps(report)
    assert report["order_lifecycle"]["closed_exact"] == 3
    if fault == "none":
        assert rc == 0 and report["approved"] is True
        assert report["prediction"]["available"] is True
        assert report["prediction"]["reason"] is None
    else:
        assert rc == 2 and report["approved"] is False
        assert report["checks"]["prediction_samples_met"] is False
        assert report["checks"]["no_prediction_backlog"] is False
        assert report["prediction"]["available"] is False
        assert report["prediction"]["failure_stage"] == "prediction_read"
        for key in ("resolved", "pending", "overdue", "expired", "expired_total"):
            assert report["prediction"][key] is None
        expected = "prediction_sqlite_unavailable" if fault in {"open", "query"} else "prediction_filesystem_unavailable"
        assert report["prediction"]["reason"] == expected


@pytest.mark.parametrize("state", ["missing", "corrupt", "empty", "legacy"])
def test_prediction_unavailable_inputs_remain_explicit(tmp_path, state):
    path = tmp_path / "synthetic.sqlite3"
    if state == "corrupt":
        path.write_bytes(b"synthetic non-SQLite input")
    elif state in {"empty", "legacy"}:
        con = sqlite3.connect(path)
        if state == "legacy":
            con.execute("CREATE TABLE prediction_outcomes (outcome_json, resolved_at_ms)")
        con.close()
    result = production_soak_report._prediction_counts(
        path, now_ms=1_800_000_000_000, soak_started_ms=1_799_000_000_000,
        maximum_settlement_delay_sec=300,
    )
    assert result["available"] is False
    assert result["backlog_verifiable"] is False
    assert result["reason"] == {
        "missing": "prediction_database_missing", "corrupt": "prediction_sqlite_unavailable",
        "empty": "prediction_schema_unavailable", "legacy": "prediction_schema_incomplete",
    }[state]
    assert result["overdue"] is None


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
