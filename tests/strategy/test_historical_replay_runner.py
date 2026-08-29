from __future__ import annotations

import json

from bin import historical_replay_runner as runner
from ladder_dragon.strategy.depth_segments import atomic_json
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


def _request(path, index: int) -> None:
    path.write_text(json.dumps({"request": index}), encoding="utf-8")


def test_runner_processes_one_immutable_request_per_cycle(tmp_path, monkeypatch):
    requests = tmp_path / "requests"
    reports = tmp_path / "reports"
    requests.mkdir()
    _request(requests / "one.json", 1)
    _request(requests / "two.json", 2)

    def replay(request_path, output_path, *, context_db):
        body = {
            "schema_version": 1,
            "status": "COMPLETE_SELECTION_REPLAY",
            "mode": "SHADOW",
            "request": json.loads(request_path.read_text(encoding="utf-8")),
            "context_db_present": context_db.name == "context.sqlite3",
        }
        body["report_sha256"] = fingerprint(body)
        atomic_json(output_path, body)
        return body

    monkeypatch.setattr(runner, "run_replay_request", replay)
    context_db = tmp_path / "context.sqlite3"

    first = runner.process_requests(requests, reports, context_db)
    assert first["new_report_count"] == 1
    assert first["selection_import_automatic"] is False
    assert len(list(reports.glob("*.json"))) == 2  # One report plus status.

    second = runner.process_requests(requests, reports, context_db)
    assert second["new_report_count"] == 1
    assert second["completed_report_count"] == 2
    assert second["operator_review_ready"] is False


def test_runner_fails_closed_on_corrupt_existing_report(tmp_path):
    requests = tmp_path / "requests"
    reports = tmp_path / "reports"
    requests.mkdir()
    reports.mkdir()
    request = requests / "one.json"
    _request(request, 1)
    reports.joinpath(runner._identity(request) + ".json").write_text(
        "{}", encoding="utf-8"
    )

    status = runner.process_requests(
        requests, reports, tmp_path / "context.sqlite3"
    )

    assert status["failed_request_count"] == 1
    assert status["completed_report_count"] == 0
    assert status["status"] == "BLOCKED"
    assert status["operator_review_ready"] is False
    serialized = json.dumps(status).lower()
    assert "secret" not in serialized
    assert str(tmp_path).lower() not in serialized
