from collections import defaultdict
import json

from ladder_dragon.strategy.prediction import historical_replay_planner as planner
from ladder_dragon.strategy.prediction.episode_semantics import (
    v23_evidence_semantics_contract,
)
from ladder_dragon.strategy.prediction.historical_entry_replay import MODEL_CONTRACT
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_selection import (
    historical_selection_artifact,
)


def _path_chains(tmp_path, count: int):
    duration = (
        planner.SIGNAL_WARMUP_MS
        + planner.PATH_ENTRY_WINDOW_MS
        + planner.TERMINAL_TAIL_MS
    )
    chains = []
    for index in range(count):
        start = 1_000_000 + index * (duration + 60_000)
        archive = tmp_path / f"segment-{index}.jsonl"
        archive.write_text("public", encoding="utf-8")
        chains.append([(
            archive,
            {
                "started_at_ms": start,
                "finished_at_ms": start + duration,
                "archive_sha256": format(index + 1, "064x"),
            },
        )])
    return chains


def _replay_report(request: dict) -> dict:
    baseline = []
    veto = []
    for index, path in enumerate(request["paths"]):
        stamp = path["start_ms"]
        baseline.append({
            "episode_id": f"baseline-{index}",
            "started_at_ms": stamp,
            "net_pnl_quote": "-1",
            "censored": False,
            "terminal_reason": "STOP_LIMIT",
        })
        veto.append({
            "episode_id": f"veto-{index}",
            "started_at_ms": stamp,
            "net_pnl_quote": "1",
            "censored": False,
            "terminal_reason": "ENTRY_VETO" if index == 0 else "TAKE_PROFIT",
        })
    windows = [{
        "start_ts_ms": path["start_ms"],
        "entry_end_ts_ms": path["entry_end_ms"],
        "end_ts_ms": path["end_ms"],
        "cutoff_ts_ms": path["cutoff_ms"],
        "source_sha256s": [row["sha256"] for row in path["archives"]],
    } for path in request["paths"]]
    body = {
        "schema_version": 2,
        "model_contract": MODEL_CONTRACT,
        "cohort_contract": planner.COHORT_CONTRACT,
        "stability_block_index": request["stability_block_index"],
        "status": "COMPLETE_SELECTION_REPLAY",
        "mode": "SHADOW",
        "apply_allowed": False,
        "promotion_eligible": False,
        "selection_artifact_ready": False,
        "policy": request["policy"],
        "policy_sha256": fingerprint(request["policy"]),
        "model_source_sha256s": {"model.py": "c" * 64},
        "source_sha256s": [
            value for window in windows for value in window["source_sha256s"]
        ],
        "path_windows": windows,
        "start_ts_ms": windows[0]["start_ts_ms"],
        "entry_end_ts_ms": windows[-1]["entry_end_ts_ms"],
        "end_ts_ms": windows[-1]["end_ts_ms"],
        "cutoff_ts_ms": windows[-1]["cutoff_ts_ms"],
        "summaries": {
            "baseline": {"opportunities": 3},
            "veto": {"opportunities": 3},
        },
        "episodes": {"baseline": baseline, "veto": veto},
    }
    return {**body, "report_sha256": fingerprint(body)}


def test_planner_creates_provider_bounded_review_drafts(tmp_path, monkeypatch):
    chains = _path_chains(tmp_path, planner.MINIMUM_INDEPENDENT_PATHS)
    monkeypatch.setattr(planner, "_chains", lambda *_args: chains)
    classifier = fingerprint(
        v23_evidence_semantics_contract()["regime_classifier"]
    )

    def context(*_args, **kwargs):
        assert kwargs["classifier_fingerprint"] == classifier
        return {"context": [{
            "classifier_fingerprint": classifier,
            "panic_source_fingerprint": "b" * 64,
        }]}

    monkeypatch.setattr(planner, "export_context", context)
    draft_directory = tmp_path / "drafts"

    report = planner.plan_replay_drafts(
        tmp_path, draft_directory, tmp_path / "context.sqlite3"
    )

    drafts = list(draft_directory.glob("*.json"))
    assert report["status"] == "DRAFTS_READY_FOR_OPERATOR_REVIEW"
    assert report["draft_count"] == 144
    assert report["complete_independent_paths"] == 12
    assert report["cohort_contract"] == planner.COHORT_CONTRACT
    assert len(drafts) == 144
    assert report["automatic_queueing"] is False
    assert report["automatic_selection_import"] is False
    assert not (tmp_path / "requests").exists()

    by_policy = defaultdict(list)
    for path in drafts:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request["request_schema_version"] == 2
        assert len(request["paths"]) == 3
        by_policy[fingerprint(request["policy"])].append(request)
    requests = next(rows for rows in by_policy.values() if len(rows) == 4)
    requests.sort(key=lambda row: row["stability_block_index"])
    artifact = historical_selection_artifact(
        [_replay_report(request) for request in requests],
        source_generation="v22",
        candidate_fingerprint="d" * 64,
        cutoff_ts_ms=max(
            path["cutoff_ms"] for request in requests for path in request["paths"]
        ),
    )
    assert artifact["schema_version"] == 3
    assert artifact["selection_metrics"]["independent_paths"] == 12
    assert artifact["selection_metrics"]["report_blocks"] == 4
    assert artifact["selected_rule"]["signal_window_ms"] == 300_000


def test_planner_reports_existing_partial_path_progress(tmp_path, monkeypatch):
    chains = _path_chains(tmp_path, 6)
    monkeypatch.setattr(planner, "_chains", lambda *_args: chains)

    report = planner.plan_replay_drafts(
        tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
    )

    assert report["status"] == "COLLECTING_DISJOINT_CONTINUOUS_BLOCKS"
    assert report["complete_independent_paths"] == 6
    assert report["complete_blocks"] == 2
    assert report["draft_count"] == 0


def test_planner_preflight_reports_an_unreachable_provider_design(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(planner, "PROVIDER_CONNECTION_MAX_MS", 60_000)

    report = planner.plan_replay_drafts(
        tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
    )

    assert report["status"] == "DESIGN_UNREACHABLE"
    assert report["reachable"] is False
    assert report["draft_count"] == 0
