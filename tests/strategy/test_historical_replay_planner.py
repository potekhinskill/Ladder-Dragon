from collections import defaultdict
import json
from pathlib import Path

import pytest

from ladder_dragon.strategy.prediction import historical_replay_planner as planner
from ladder_dragon.strategy.prediction.episode_semantics import (
    v23_evidence_semantics_contract,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_entry_replay import MODEL_CONTRACT
from ladder_dragon.strategy.prediction.historical_selection import (
    historical_selection_artifact,
)


def test_planner_creates_review_drafts_without_queueing_or_importing(
    tmp_path, monkeypatch
):
    archive = tmp_path / "segment.jsonl"
    archive.write_text("public", encoding="utf-8")
    blocks = []
    for index in range(planner.BLOCK_COUNT):
        start = 1_000_000 + index * 100_000_000
        finish = (
            start + planner.SIGNAL_WARMUP_MS + planner.ENTRY_WINDOW_MS
            + planner.TERMINAL_TAIL_MS
        )
        metadata = {
            "started_at_ms": start,
            "finished_at_ms": finish,
            "archive_sha256": format(index + 1, "064x"),
        }
        blocks.append([(archive, metadata)])
    monkeypatch.setattr(planner, "_chains", lambda *_args: blocks)
    classifier = fingerprint(
        v23_evidence_semantics_contract()["regime_classifier"]
    )

    def context(*_args, **kwargs):
        assert kwargs["classifier_fingerprint"] == classifier
        return {
            "context": [{
                "classifier_fingerprint": classifier,
                "panic_source_fingerprint": "b" * 64,
            }]
        }

    monkeypatch.setattr(planner, "export_context", context)
    draft_directory = tmp_path / "drafts"

    report = planner.plan_replay_drafts(
        tmp_path, draft_directory, tmp_path / "context.sqlite3"
    )

    drafts = list(draft_directory.glob("*.json"))
    assert report["status"] == "DRAFTS_READY_FOR_OPERATOR_REVIEW"
    assert report["draft_count"] == 144
    assert len(drafts) == 144
    assert report["maximum_reachable_independent_paths"] == 12
    assert report["required_independent_paths"] == 12
    assert report["automatic_queueing"] is False
    assert report["automatic_selection_import"] is False
    assert not (tmp_path / "requests").exists()

    by_policy = defaultdict(list)
    for path in drafts:
        request = json.loads(path.read_text(encoding="utf-8"))
        by_policy[fingerprint(request["policy"])].append(request)
    requests = next(rows for rows in by_policy.values() if len(rows) == 4)
    replay_reports = []
    for request in sorted(requests, key=lambda row: row["start_ms"]):
        veto = []
        baseline = []
        for index in range(3):
            stamp = request["start_ms"] + index * planner.INDEPENDENCE_SPACING_MS
            veto.append({
                "started_at_ms": stamp,
                "net_pnl_quote": "1",
                "censored": False,
                "terminal_reason": "ENTRY_VETO" if index == 0 else "TAKE_PROFIT",
            })
            baseline.append({
                "started_at_ms": stamp,
                "net_pnl_quote": "-1",
                "censored": False,
                "terminal_reason": "STOP_LIMIT",
            })
        body = {
            "schema_version": 1,
            "model_contract": MODEL_CONTRACT,
            "status": "COMPLETE_SELECTION_REPLAY",
            "mode": "SHADOW",
            "apply_allowed": False,
            "promotion_eligible": False,
            "selection_artifact_ready": False,
            "policy": request["policy"],
            "policy_sha256": fingerprint(request["policy"]),
            "model_source_sha256s": {"model.py": "c" * 64},
            "source_sha256s": [row["sha256"] for row in request["archives"]],
            "start_ts_ms": request["start_ms"],
            "entry_end_ts_ms": request["entry_end_ms"],
            "end_ts_ms": request["end_ms"],
            "cutoff_ts_ms": request["cutoff_ms"],
            "summaries": {
                "baseline": {"opportunities": 10},
                "veto": {"opportunities": 10},
            },
            "episodes": {"baseline": baseline, "veto": veto},
        }
        replay_reports.append({**body, "report_sha256": fingerprint(body)})
    artifact = historical_selection_artifact(
        replay_reports,
        source_generation="v22",
        candidate_fingerprint="d" * 64,
        cutoff_ts_ms=max(row["cutoff_ms"] for row in requests),
    )
    assert artifact["selection_metrics"]["independent_paths"] == 12
    assert artifact["selected_rule"]["signal_window_ms"] == 300_000


def test_planner_preflight_rejects_an_unreachable_design(tmp_path, monkeypatch):
    monkeypatch.setattr(planner, "ENTRY_WINDOW_MS", 12 * 60 * 60_000)
    with pytest.raises(ValueError, match="mathematically unreachable"):
        planner.plan_replay_drafts(
            tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
        )
