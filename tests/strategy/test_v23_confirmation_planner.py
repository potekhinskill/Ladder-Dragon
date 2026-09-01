import pytest

from ladder_dragon.strategy.prediction import v23_confirmation_planner as subject


def _manifest():
    return {
        "confirmation_start_ts_ms": 1_000,
        "confirmation_deadline_ts_ms": 1_000 + 15 * 24 * 60 * 60_000,
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
        "candidate_parameters": {
            "entry_gap_bps": "48",
            "target_return": "0.008",
            "stop_limit_distance": "0.01035",
            "stop_trigger_offset_pct": "0.0015",
            "evidence_notional_quote": "6",
            "entry_ttl_sec": 5_400,
            "maximum_holding_min": 360,
            "regime_policy": "range_only",
            "entry_veto_rule": {
                "selection_artifact_sha256": "a" * 64,
                "prefill_price_change_max_bps": "-10",
                "prefill_signed_trade_flow_max": "-0.2",
                "prefill_order_flow_imbalance_max": "-0.3",
                "cancel_latency_ms": 1_000,
                "signal_window_ms": 300_000,
            },
        },
    }


def _ready_paths(tmp_path, count):
    rows = []
    for index in range(count):
        start = 10_000 + index * 30_000_000
        archive = tmp_path / f"confirmation-{index}.jsonl"
        archive.write_text("public", encoding="utf-8")
        path = (
            start,
            start + subject.PATH_ENTRY_WINDOW_MS,
            start + subject.PATH_ENTRY_WINDOW_MS + subject.TERMINAL_TAIL_MS,
            [(archive, {"archive_sha256": format(index + 1, "064x")})],
        )
        context = {
            "classifier_fingerprint": "b" * 64,
            "panic_source_fingerprint": "c" * 64,
        }
        rows.append((path, context))
    return rows


def test_confirmation_planner_waits_before_v23_is_frozen(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(subject, "find_active_v23_manifest", lambda _store: None)

    report = subject.plan_v23_confirmation_drafts(
        object(), tmp_path, tmp_path / "confirmation-drafts",
        tmp_path / "context.sqlite3",
    )

    assert report["status"] == "WAITING_V23_SELECTION_ARTIFACT"
    assert report["draft_count"] == 0


def test_confirmation_planner_freezes_post_cutoff_criteria_sized_cohort(
    tmp_path, monkeypatch
):
    manifest = _manifest()
    ready = _ready_paths(tmp_path, 42)
    monkeypatch.setattr(
        subject, "find_active_v23_manifest", lambda _store: manifest
    )
    monkeypatch.setattr(
        subject,
        "load_v23_selection_artifact",
        lambda *_args: {
            "schema_version": 5,
            "source_archive_sha256s": ["f" * 64],
            "model_source_sha256s": {"model.py": "e" * 64},
            "selection_metrics": {
                "confirmation_capacity_policy": (
                    subject.V23_CONFIRMATION_CAPACITY_POLICY
                ),
                "eligible_path_rate_lower_bound": "1",
                "filled_path_rate_lower_bound": "1",
                "range_filled_path_rate_lower_bound": "1",
            },
        },
    )
    monkeypatch.setattr(subject, "_chains", lambda *_args: [[]])

    def context(*_args, **kwargs):
        assert kwargs["started_after_ms"] == 1_000
        assert kwargs["excluded_source_sha256s"] == frozenset(["f" * 64])
        assert kwargs["maximum_ready_paths"] == 42
        assert kwargs["newest_first"] is False
        return ready, {
            "l2_complete_independent_paths": 42,
            "context_checked_paths": 42,
            "context_ready_independent_paths": 42,
            "executable_ready_independent_paths": 42,
            "context_rejected_path_counts": {},
        }

    monkeypatch.setattr(subject, "context_ready_paths", context)
    draft_directory = tmp_path / "confirmation-drafts"

    report = subject.plan_v23_confirmation_drafts(
        object(), tmp_path, draft_directory, tmp_path / "context.sqlite3"
    )

    drafts = list(draft_directory.glob("*.json"))
    assert report["status"] == "CONFIRMATION_COHORT_COMPLETE"
    assert report["required_independent_paths"] == 42
    assert report["minimum_structural_pass_paths"] == 24
    assert report["draft_count"] == 14
    assert len(drafts) == 14
    assert report["automatic_queueing"] is True
    assert report["automatic_confirmation_import"] is True
    assert len(list((tmp_path / "confirmation-requests").glob("*.json"))) == 14
    marker = subject.bounded_json(
        draft_directory.parent / subject.CONFIRMATION_COHORT_MARKER
    )
    assert marker["schema_version"] == (
        subject.V23_CONFIRMATION_COHORT_SCHEMA_VERSION
    )
    assert marker["confirmation_capacity_design"]["dynamic_top_up_allowed"] is False


def test_confirmation_capacity_is_fixed_before_selection_outcomes():
    selection = {
        "schema_version": 5,
        "selection_metrics": {
            "confirmation_capacity_policy": (
                subject.V23_CONFIRMATION_CAPACITY_POLICY
            ),
            "eligible_path_rate_lower_bound": "0.833333333333333333",
            "filled_path_rate_lower_bound": "0.583333333333333333",
            "range_filled_path_rate_lower_bound": "0.583333333333333333",
        },
    }

    design = subject._confirmation_design(_manifest(), selection)

    assert design["required_independent_paths"] == 42
    assert design["minimum_structural_pass_paths"] == 24
    assert design["design_effect_target_filled_episodes"] == 29
    assert design["design_effect_is_capacity_gate"] is False
    assert design["dynamic_top_up_allowed"] is False


def test_provider_capacity_rejects_more_than_42_paths_in_14_days():
    duration = 14 * 24 * 60 * 60_000

    capacity = subject._provider_capacity(duration)

    assert capacity["paths_per_provider_session"] == 3
    assert capacity["maximum_paths_before_deadline"] == 42
    assert subject._provider_design_duration(42) <= duration
    assert subject._provider_design_duration(43) > duration


def test_remaining_capacity_uses_the_current_provider_session_remainder():
    now = 10 * 60 * 60_000
    deadline = 30 * 60 * 60_000
    chains = [[(
        None,
        {
            "started_at_ms": 1,
            "finished_at_ms": now - 60_000,
        },
    )]]

    capacity = subject._remaining_provider_capacity(
        chains, now_ms=now, deadline_ms=deadline
    )

    assert capacity["current_session_detected"] is True
    assert capacity["maximum_paths_before_deadline"] == 2
    assert capacity["current_session_remaining_ms"] == (
        subject.PROVIDER_CONNECTION_MAX_MS + 1 - now
    )


def test_remaining_capacity_counts_an_in_progress_first_path():
    now = 6 * 60 * 60_000
    deadline = subject.PROVIDER_CONNECTION_MAX_MS + 1
    chains = [[(
        None,
        {
            "started_at_ms": 1,
            "finished_at_ms": now - 60_000,
        },
    )]]

    capacity = subject._remaining_provider_capacity(
        chains, now_ms=now, deadline_ms=deadline
    )

    assert capacity["current_session_detected"] is True
    assert capacity["maximum_paths_before_deadline"] == 3


def test_confirmation_planner_queues_first_complete_block_immediately(
    tmp_path, monkeypatch
):
    manifest = _manifest()
    ready = _ready_paths(tmp_path, 3)
    monkeypatch.setattr(
        subject, "find_active_v23_manifest", lambda _store: manifest
    )
    monkeypatch.setattr(
        subject, "load_v23_selection_artifact", lambda *_args: {
            "schema_version": 5,
            "source_archive_sha256s": ["f" * 64],
            "selection_metrics": {
                "confirmation_capacity_policy": (
                    subject.V23_CONFIRMATION_CAPACITY_POLICY
                ),
                "eligible_path_rate_lower_bound": "1",
                "filled_path_rate_lower_bound": "1",
                "range_filled_path_rate_lower_bound": "1",
            },
        },
    )
    monkeypatch.setattr(subject, "_chains", lambda *_args: [[]])
    monkeypatch.setattr(
        subject, "context_ready_paths", lambda *_args, **_kwargs: (
            ready,
            {
                "l2_complete_independent_paths": 3,
                "context_checked_paths": 3,
                "context_ready_independent_paths": 3,
                "executable_ready_independent_paths": 3,
                "context_rejected_path_counts": {},
            },
        ),
    )

    report = subject.plan_v23_confirmation_drafts(
        object(), tmp_path, tmp_path / "confirmation-drafts",
        tmp_path / "context.sqlite3", now_ms=10_000,
    )

    assert report["status"] == "STREAMING_CONFIRMATION_BLOCKS"
    assert report["queued_block_count"] == 1
    assert report["complete_independent_paths"] == 3
    assert len(list((tmp_path / "confirmation-requests").glob("*.json"))) == 1


@pytest.mark.parametrize(
    ("remaining", "expected", "pass_futile", "fixed_shortfall"),
    [
        (20, "READY_TO_REJECT_PASS_CAPACITY", True, True),
        (25, "FIXED_COHORT_CAPACITY_SHORTFALL", False, True),
    ],
)
def test_confirmation_separates_pass_futility_from_full_cohort_shortfall(
    tmp_path, monkeypatch, remaining, expected, pass_futile, fixed_shortfall
):
    manifest = _manifest()
    ready = _ready_paths(tmp_path, 3)
    monkeypatch.setattr(
        subject, "find_active_v23_manifest", lambda _store: manifest
    )
    monkeypatch.setattr(
        subject, "load_v23_selection_artifact", lambda *_args: {
            "schema_version": 5,
            "source_archive_sha256s": ["f" * 64],
            "selection_metrics": {
                "confirmation_capacity_policy": (
                    subject.V23_CONFIRMATION_CAPACITY_POLICY
                ),
                "eligible_path_rate_lower_bound": "1",
                "filled_path_rate_lower_bound": "1",
                "range_filled_path_rate_lower_bound": "1",
            },
        },
    )
    monkeypatch.setattr(subject, "_chains", lambda *_args: [[]])
    monkeypatch.setattr(
        subject, "context_ready_paths", lambda *_args, **_kwargs: (
            ready,
            {
                "l2_complete_independent_paths": 3,
                "context_checked_paths": 3,
                "context_ready_independent_paths": 3,
                "executable_ready_independent_paths": 3,
                "context_rejected_path_counts": {},
            },
        ),
    )
    monkeypatch.setattr(
        subject,
        "_remaining_provider_capacity",
        lambda *_args, **_kwargs: {
            "maximum_paths_before_deadline": remaining,
            "current_session_detected": False,
            "current_session_started_at_ms": None,
            "current_session_remaining_ms": None,
        },
    )

    report = subject.plan_v23_confirmation_drafts(
        object(), tmp_path, tmp_path / "confirmation-drafts",
        tmp_path / "context.sqlite3", now_ms=10_000,
    )

    assert report["status"] == expected
    assert report["pass_capacity_futile"] is pass_futile
    assert report["fixed_cohort_capacity_shortfall"] is fixed_shortfall


def test_planner_rejects_when_minimum_pass_capacity_is_unreachable(
    tmp_path, monkeypatch
):
    manifest = _manifest()
    manifest["confirmation_deadline_ts_ms"] = (
        manifest["confirmation_start_ts_ms"] + 8 * 24 * 60 * 60_000
    )
    monkeypatch.setattr(
        subject, "find_active_v23_manifest", lambda _store: manifest
    )
    monkeypatch.setattr(
        subject,
        "load_v23_selection_artifact",
        lambda *_args: {
            "schema_version": 5,
            "selection_metrics": {
                "confirmation_capacity_policy": (
                    subject.V23_CONFIRMATION_CAPACITY_POLICY
                ),
                "eligible_path_rate_lower_bound": "0.833333333333333333",
                "filled_path_rate_lower_bound": "0.583333333333333333",
                "range_filled_path_rate_lower_bound": "0.583333333333333333",
            },
        },
    )

    report = subject.plan_v23_confirmation_drafts(
        object(), tmp_path, tmp_path / "confirmation-drafts",
        tmp_path / "context.sqlite3",
    )

    assert report["status"] == "DESIGN_UNREACHABLE"
    assert report["required_independent_paths"] == 42
    assert report["minimum_structural_pass_paths"] == 24
    assert report["provider_capacity"]["maximum_paths_before_deadline"] == 24


def test_confirmation_stage_counts_do_not_treat_report_files_as_evaluated(
    tmp_path,
):
    reports = tmp_path / "confirmation-reports"
    reports.mkdir()
    subject.atomic_json(reports / "status.json", {
        "import_mode": "automatic_confirmation",
        "completed_report_count": 2,
    })
    subject.atomic_json(tmp_path / "confirmation-import-status.json", {
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
        "hash_verified_block_count": 1,
        "imported_block_count": 1,
        "statistically_evaluated_block_count": 0,
    })

    stages = subject._confirmation_stage_counts(tmp_path, 3)

    assert stages == {
        "queued_block_count": 3,
        "replay_completed_block_count": 2,
        "hash_verified_block_count": 1,
        "imported_block_count": 1,
        "statistically_evaluated_block_count": 0,
    }
