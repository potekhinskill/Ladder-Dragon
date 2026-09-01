from collections import defaultdict
from decimal import Decimal
import json

import pytest

from ladder_dragon.strategy.prediction import historical_replay_planner as planner
from ladder_dragon.strategy.prediction import v23_confirmation_planner
from ladder_dragon.strategy.prediction.episode_semantics import (
    v23_evidence_semantics_contract,
)
from ladder_dragon.strategy.prediction.historical_entry_replay import MODEL_CONTRACT
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_selection import (
    historical_selection_artifact,
)
from ladder_dragon.strategy.prediction.v23_contract import (
    V23_CONFIRMATION_CAPACITY_POLICY,
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
                "finished_at_ms": start + duration + planner.ENTRY_CADENCE_MS,
                "archive_sha256": format(index + 1, "064x"),
            },
        )])
    return chains


def _context_row(*, regime="RANGE", panic=False, start=0, end=10**15):
    return {
        "observed_at_ms": start,
        "valid_until_ms": end,
        "regime": regime,
        "panic": panic,
        "classifier_fingerprint": fingerprint(
            v23_evidence_semantics_contract()["regime_classifier"]
        ),
        "panic_source_fingerprint": "b" * 64,
    }


@pytest.fixture(autouse=True)
def _continuous_context(monkeypatch):
    monkeypatch.setattr(
        planner,
        "continuous_context_intervals",
        lambda *_args, **kwargs: [{
            "start_ms": kwargs["start_ms"],
            "end_ms": kwargs["end_ms"] + 1,
            "session_id": "a" * 32,
            "classifier_fingerprint": kwargs["classifier_fingerprint"],
            "panic_source_fingerprint": "b" * 64,
        }],
    )


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
            "eligible_for_promotion": True,
            "start_regime": "RANGE",
            "entry_filled_quantity": "1",
            "entry_order_submitted": True,
            "signal_ts_ms": None,
            "cancel_effective_ts_ms": None,
        })
        veto.append({
            "episode_id": f"veto-{index}",
            "started_at_ms": stamp,
            "net_pnl_quote": "1",
            "censored": False,
            "terminal_reason": "ENTRY_VETO" if index == 0 else "TAKE_PROFIT",
            "eligible_for_promotion": True,
            "start_regime": "RANGE",
            "entry_filled_quantity": "0" if index == 0 else "1",
            "entry_order_submitted": index != 0,
            "signal_ts_ms": stamp if index == 0 else None,
            "cancel_effective_ts_ms": None,
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
        return {"context": [_context_row()]}

    monkeypatch.setattr(planner, "export_context", context)
    draft_directory = tmp_path / "drafts"

    report = planner.plan_replay_drafts(
        tmp_path, draft_directory, tmp_path / "context.sqlite3"
    )

    drafts = list(draft_directory.glob("*.json"))
    assert report["status"] == "DRAFTS_READY_FOR_OPERATOR_REVIEW"
    assert report["draft_count"] == 32
    assert report["complete_independent_paths"] == 12
    assert report["cohort_contract"] == planner.COHORT_CONTRACT
    assert len(drafts) == 32
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
    assert artifact["schema_version"] == 5
    assert artifact["selection_metrics"]["confirmation_capacity_policy"] == (
        V23_CONFIRMATION_CAPACITY_POLICY
    )
    assert artifact["selection_metrics"]["independent_paths"] == 12
    assert artifact["selection_metrics"]["report_blocks"] == 4
    assert Decimal(
        artifact["selection_metrics"]["filled_path_rate_lower_bound"]
    ) < Decimal("7") / Decimal("12")
    assert artifact["selection_metrics"]["planning_rate_hypotheses"] == 3
    assert artifact["selection_metrics"]["confirmation_preflight_ready"] is True
    assert artifact["selected_rule"]["signal_window_ms"] == 300_000
    design = v23_confirmation_planner._confirmation_design({
        "criteria": {
            "criteria_schema_version": 8,
            "minimum_eligible_terminal_episodes": 24,
            "minimum_filled_episodes": 10,
            "minimum_regime_filled_episodes": 12,
            "minimum_confirmed_regimes": 1,
            "design_effect_required_filled_episodes": 29,
            "maximum_terminal_episodes": 42,
            "confirmation_cohort_policy": "bounded_provider_capacity_paths_v2",
            "fixed_confirmation_paths": 42,
            "minimum_structural_pass_paths": 24,
            "dynamic_confirmation_top_up_allowed": False,
            "design_effect_is_capacity_gate": False,
            "provider_capacity_reserve_paths": 3,
            "confirmation_block_size": 3,
            "incremental_block_evaluation": True,
            "path_admission_policy": (
                "first_causal_executable_cadence_opportunity_v4"
            ),
            "path_trial_cardinality_policy": (
                "one_terminal_attempt_per_executable_path_v1"
            ),
            "confirmation_evidence_origin_policy": (
                "immutable_l2_path_reports_only_v1"
            ),
        },
    }, artifact)
    assert design["required_independent_paths"] == 42


def test_selection_rejects_insufficient_confirmation_capacity(
    tmp_path, monkeypatch,
):
    chains = _path_chains(tmp_path, planner.MINIMUM_INDEPENDENT_PATHS)
    monkeypatch.setattr(planner, "_chains", lambda *_args: chains)
    monkeypatch.setattr(planner, "export_context", lambda *_args, **_kwargs: {
        "context": [_context_row()],
    })
    draft_directory = tmp_path / "drafts"
    planner.plan_replay_drafts(
        tmp_path, draft_directory, tmp_path / "context.sqlite3"
    )
    requests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in draft_directory.glob("*.json")
    ]
    by_policy = defaultdict(list)
    for request in requests:
        by_policy[fingerprint(request["policy"])].append(request)
    cohort = next(rows for rows in by_policy.values() if len(rows) == 4)
    cohort.sort(key=lambda row: row["stability_block_index"])
    reports = [_replay_report(request) for request in cohort]
    reports[0]["episodes"]["veto"][1]["entry_filled_quantity"] = "0"
    reports[0]["episodes"]["veto"][1]["terminal_reason"] = "ENTRY_VETO"
    reports[0]["episodes"]["veto"][1]["entry_order_submitted"] = False
    reports[0]["episodes"]["veto"][1]["signal_ts_ms"] = reports[0][
        "episodes"
    ]["veto"][1]["started_at_ms"]
    reports[0]["episodes"]["veto"][1]["cancel_effective_ts_ms"] = None
    reports[0]["report_sha256"] = fingerprint({
        key: value for key, value in reports[0].items()
        if key != "report_sha256"
    })

    with pytest.raises(ValueError, match="selection criteria are incomplete"):
        historical_selection_artifact(
            reports,
            source_generation="v22",
            candidate_fingerprint="d" * 64,
            cutoff_ts_ms=max(
                path["cutoff_ms"]
                for request in cohort for path in request["paths"]
            ),
        )


def test_planner_reports_existing_partial_path_progress(tmp_path, monkeypatch):
    chains = _path_chains(tmp_path, 6)
    monkeypatch.setattr(planner, "_chains", lambda *_args: chains)
    monkeypatch.setattr(planner, "export_context", lambda *_args, **_kwargs: {
        "context": [_context_row()],
    })

    report = planner.plan_replay_drafts(
        tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
    )

    assert report["status"] == "COLLECTING_EXECUTABLE_CONTEXT_PATHS"
    assert report["complete_independent_paths"] == 6
    assert report["l2_complete_independent_paths"] == 6
    assert report["context_ready_independent_paths"] == 6
    assert report["executable_ready_independent_paths"] == 6
    assert report["complete_blocks"] == 2
    assert report["draft_count"] == 0


def test_planner_does_not_count_l2_paths_without_exportable_context(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        planner, "_chains", lambda *_args: _path_chains(tmp_path, 6)
    )
    monkeypatch.setattr(
        planner,
        "export_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("context interval contains unavailable evidence")
        ),
    )

    report = planner.plan_replay_drafts(
        tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
    )

    assert report["l2_complete_independent_paths"] == 6
    assert report["context_ready_independent_paths"] == 0
    assert report["complete_independent_paths"] == 0
    assert report["context_rejected_path_counts"] == {
        "CONTEXT_UNAVAILABLE": 6
    }


def test_planner_freezes_one_draft_cohort_instead_of_rolling(
    tmp_path, monkeypatch
):
    chains = _path_chains(tmp_path, planner.MINIMUM_INDEPENDENT_PATHS)
    monkeypatch.setattr(planner, "_chains", lambda *_args: chains)
    classifier = fingerprint(
        v23_evidence_semantics_contract()["regime_classifier"]
    )
    monkeypatch.setattr(planner, "export_context", lambda *_args, **_kwargs: {
        "context": [_context_row()],
    })
    drafts = tmp_path / "drafts"
    first = planner.plan_replay_drafts(
        tmp_path, drafts, tmp_path / "context.sqlite3"
    )
    shifted = _path_chains(tmp_path, planner.MINIMUM_INDEPENDENT_PATHS)
    for chain in shifted:
        chain[0][1]["started_at_ms"] += 86_400_000
        chain[0][1]["finished_at_ms"] += 86_400_000
    monkeypatch.setattr(planner, "_chains", lambda *_args: shifted)

    second = planner.plan_replay_drafts(
        tmp_path, drafts, tmp_path / "context.sqlite3"
    )

    assert first["draft_count"] == 32
    assert second["status"] == "DRAFT_COHORT_FROZEN_FOR_REVIEW"
    assert len([path for path in drafts.glob("*.json") if path.name != "status.json"]) == 32


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


def test_planner_rejects_context_without_an_executable_entry_interval(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        planner, "_chains", lambda *_args: _path_chains(tmp_path, 2)
    )
    rows = iter([
        {"context": [_context_row(regime="TREND_DOWN")]},
        {"context": [_context_row(regime="RANGE", panic=True)]},
    ])
    monkeypatch.setattr(
        planner, "export_context", lambda *_args, **_kwargs: next(rows)
    )

    report = planner.plan_replay_drafts(
        tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
    )

    assert report["complete_independent_paths"] == 0
    assert report["context_ready_independent_paths"] == 0
    assert report["executable_ready_independent_paths"] == 0
    assert report["context_rejected_path_counts"] == {
        "NO_EXECUTABLE_ENTRY_CONTEXT": 2
    }


def test_planner_accepts_range_only_when_it_overlaps_the_entry_window(
    tmp_path, monkeypatch
):
    chains = _path_chains(tmp_path, 1)
    start = chains[0][0][1]["started_at_ms"] + planner.SIGNAL_WARMUP_MS
    chains[0][0][1]["finished_at_ms"] += 2 * 60 * 60_000
    monkeypatch.setattr(planner, "_chains", lambda *_args: chains)
    monkeypatch.setattr(planner, "export_context", lambda *_args, **_kwargs: {
        "context": [
            _context_row(
                regime="TREND_DOWN", start=start, end=start + 60_000
            ),
                _context_row(
                    regime="RANGE", start=start + 60_000,
                    end=start + 10 * 60_000,
                ),
        ],
    })

    report = planner.plan_replay_drafts(
        tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
    )

    assert report["complete_independent_paths"] == 1
    assert report["executable_ready_independent_paths"] == 1


def test_planner_reserves_sources_after_the_first_executable_opportunity(
    tmp_path, monkeypatch
):
    segment_ms = 55 * 60_000
    chain_start = 1_000_000
    chain = []
    for index in range(20):
        archive = tmp_path / f"opportunity-{index}.jsonl"
        archive.write_text("public", encoding="utf-8")
        chain.append((archive, {
            "started_at_ms": chain_start + index * segment_ms,
            "finished_at_ms": chain_start + (index + 1) * segment_ms,
            "archive_sha256": format(index + 1, "064x"),
        }))
    range_start = chain_start + 2 * 60 * 60_000
    monkeypatch.setattr(planner, "_chains", lambda *_args: [chain])

    def exported(*_args, **_kwargs):
        return {"context": [
            _context_row(
                regime="TREND_DOWN",
                start=chain_start,
                end=range_start,
            ),
            _context_row(
                regime="RANGE",
                start=range_start,
                end=chain[-1][1]["finished_at_ms"] + 1,
            ),
        ]}

    monkeypatch.setattr(planner, "export_context", exported)

    paths, progress = planner.context_ready_paths(
        [chain], tmp_path / "context.sqlite3",
        maximum_ready_paths=1,
        newest_first=False,
    )

    assert len(paths) == 1
    path, _context = paths[0]
    expected_start = (
        (range_start + planner.ENTRY_CADENCE_MS - 1)
        // planner.ENTRY_CADENCE_MS
    ) * planner.ENTRY_CADENCE_MS
    assert path[0] == expected_start
    assert path[3][0][1]["started_at_ms"] <= (
        expected_start - planner.SIGNAL_WARMUP_MS
    )
    assert path[3][0][1]["finished_at_ms"] > (
        expected_start - planner.SIGNAL_WARMUP_MS
    )
    assert progress["context_rejected_path_counts"] == {}


def test_planner_rejects_range_that_ends_before_the_next_cadence(
    tmp_path, monkeypatch
):
    chains = _path_chains(tmp_path, 1)
    earliest = (
        chains[0][0][1]["started_at_ms"] + planner.SIGNAL_WARMUP_MS
    )
    range_start = earliest + 30_000
    next_cadence = (
        (range_start + planner.ENTRY_CADENCE_MS - 1)
        // planner.ENTRY_CADENCE_MS
    ) * planner.ENTRY_CADENCE_MS
    monkeypatch.setattr(planner, "_chains", lambda *_args: chains)
    monkeypatch.setattr(planner, "export_context", lambda *_args, **_kwargs: {
        "context": [_context_row(
            regime="RANGE",
            start=range_start,
            end=next_cadence,
        )],
    })

    report = planner.plan_replay_drafts(
        tmp_path, tmp_path / "drafts", tmp_path / "context.sqlite3"
    )

    assert report["complete_independent_paths"] == 0
    assert report["context_rejected_path_counts"] == {
        "NO_EXECUTABLE_ENTRY_CONTEXT": 1
    }


def test_context_gap_realigns_later_source_disjoint_paths(
    tmp_path, monkeypatch
):
    segment_ms = 55 * 60_000
    chain = []
    start = 1_000_000
    for index in range(27):
        archive = tmp_path / f"gap-{index}.jsonl"
        archive.write_text("public", encoding="utf-8")
        chain.append((archive, {
            "started_at_ms": start + index * segment_ms,
            "finished_at_ms": start + (index + 1) * segment_ms,
            "archive_sha256": format(index + 1, "064x"),
        }))
    gap_start = start + 7 * 60 * 60_000 + 10 * 60_000
    gap_end = gap_start + 5 * 60_000
    monkeypatch.setattr(planner, "_chains", lambda *_args: [chain])
    monkeypatch.setattr(
        planner,
        "continuous_context_intervals",
        lambda *_args, **kwargs: [
            {
                "start_ms": start,
                "end_ms": gap_start,
                "session_id": "a" * 32,
                "classifier_fingerprint": kwargs[
                    "classifier_fingerprint"
                ],
                "panic_source_fingerprint": "b" * 64,
            },
            {
                "start_ms": gap_end,
                "end_ms": start + 27 * segment_ms + 1,
                "session_id": "a" * 32,
                "classifier_fingerprint": kwargs[
                    "classifier_fingerprint"
                ],
                "panic_source_fingerprint": "b" * 64,
            },
        ],
    )

    def exported(*_args, **kwargs):
        assert not (
            kwargs["start_ms"] < gap_end
            and kwargs["end_ms"] > gap_start
        )
        return {"context": [_context_row(
            start=kwargs["start_ms"], end=kwargs["end_ms"] + 1
        )]}

    monkeypatch.setattr(planner, "export_context", exported)
    paths, progress = planner.context_ready_paths(
        [chain], tmp_path / "context.sqlite3",
        maximum_ready_paths=3,
        newest_first=False,
    )

    assert len(paths) == 3
    assert progress["context_continuous_intervals"] == 2
    assert progress["context_aligned_independent_paths"] == 3
    source_sets = [
        {row[1]["archive_sha256"] for row in path[0][3]}
        for path in paths
    ]
    assert all(
        not left.intersection(right)
        for index, left in enumerate(source_sets)
        for right in source_sets[index + 1 :]
    )


def test_context_alignment_never_crosses_l2_reconnect(tmp_path, monkeypatch):
    chains = _path_chains(tmp_path, 2)
    monkeypatch.setattr(planner, "export_context", lambda *_args, **_kwargs: {
        "context": [_context_row()],
    })

    paths, _progress = planner.context_ready_paths(
        chains, tmp_path / "context.sqlite3",
        maximum_ready_paths=2,
        newest_first=False,
    )

    assert len(paths) == 2
    assert all(len(path[0][3]) == 1 for path in paths)
