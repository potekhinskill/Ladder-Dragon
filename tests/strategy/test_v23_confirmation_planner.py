from ladder_dragon.strategy.prediction import v23_confirmation_planner as subject


def _manifest():
    return {
        "confirmation_start_ts_ms": 1_000,
        "confirmation_deadline_ts_ms": 1_000 + 14 * 24 * 60 * 60_000,
        "criteria": {
            "minimum_eligible_terminal_episodes": 24,
            "minimum_filled_episodes": 10,
            "minimum_regime_filled_episodes": 12,
            "design_effect_required_filled_episodes": 29,
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
            start + 300_000,
            start + 22_000_000,
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
    ready = _ready_paths(tmp_path, 30)
    monkeypatch.setattr(
        subject, "find_active_v23_manifest", lambda _store: manifest
    )
    monkeypatch.setattr(
        subject,
        "load_v23_selection_artifact",
        lambda *_args: {
            "source_archive_sha256s": ["f" * 64],
            "model_source_sha256s": {"model.py": "e" * 64},
        },
    )
    monkeypatch.setattr(subject, "_chains", lambda *_args: [[]])

    def context(*_args, **kwargs):
        assert kwargs["started_after_ms"] == 1_000
        assert kwargs["excluded_source_sha256s"] == frozenset(["f" * 64])
        assert kwargs["maximum_ready_paths"] == 30
        return ready, {
            "l2_complete_independent_paths": 30,
            "context_checked_paths": 30,
            "context_ready_independent_paths": 30,
            "context_rejected_path_counts": {},
        }

    monkeypatch.setattr(subject, "context_ready_paths", context)
    draft_directory = tmp_path / "confirmation-drafts"

    report = subject.plan_v23_confirmation_drafts(
        object(), tmp_path, draft_directory, tmp_path / "context.sqlite3"
    )

    drafts = list(draft_directory.glob("*.json"))
    assert report["status"] == "CONFIRMATION_DRAFTS_READY_FOR_OPERATOR_REVIEW"
    assert report["required_independent_paths"] == 30
    assert report["draft_count"] == 10
    assert len(drafts) == 10
    assert report["automatic_queueing"] is False
    assert report["automatic_confirmation_import"] is False
