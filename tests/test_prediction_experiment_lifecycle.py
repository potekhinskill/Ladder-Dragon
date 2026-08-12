from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

import pytest

from ladder_dragon.strategy.prediction import (
    HorizonPrediction,
    PredictionFeatures,
    PredictionShadowStore,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    DEFAULT_CRITERIA,
    candidate_rule,
    canonical_json,
    confirmation_report,
    evidence_assignment,
    finalize_experiment,
    freeze_experiment,
    load_manifest,
    selection_experiment_id,
    variant_fingerprints,
)
from ladder_dragon.strategy.prediction.experiments import (
    EXPERIMENT_HORIZONS_MIN,
    SHADOW_GENERATION,
    build_shadow_variants,
)
from ladder_dragon.strategy.prediction.runtime import evaluation_end_ms


D = Decimal


def _features(timestamp: int, regime: str = "RANGE") -> PredictionFeatures:
    return PredictionFeatures(
        snapshot_ts_ms=timestamp,
        last_closed_bar_ts_ms=timestamp,
        price=D("100"),
        ema_slope=D("0"),
        ema_distance_pct=D("0"),
        adx=D("12"),
        plus_di=D("20"),
        minus_di=D("20"),
        atr_pct=D("0.003"),
        atr_change_pct=D("0"),
        vwap_deviation_pct=D("0"),
        rsi=D("50"),
        macd_histogram_pct=D("0"),
        volume_ratio=D("1"),
        orderbook_imbalance=D("0"),
        orderbook_available=True,
        trade_flow_imbalance=D("0"),
        trade_flow_available=True,
        spread_bps=D("1"),
        depth_quote=D("10000"),
        acceleration=D("0"),
        executor_panic_active=False,
        executor_panic_hits=0,
        regime=regime,
    )


def _variants():
    from ladder_dragon.strategy.prediction import TradePlan
    baseline = TradePlan(
        entry_price=D("99.70"),
        take_profit_price=D("100.5973"),
        stop_price=D("98.703"),
        notional_quote=D("10"),
        fee_pct=D("0.00075"),
        slippage_pct=D("0.0005"),
    )
    return build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
        regime="RANGE",
    )


def _predictions():
    return tuple(
        HorizonPrediction(horizon, D("1"), D("1"), D("1"), D("0"), D("1"), 120, True)
        for horizon in EXPERIMENT_HORIZONS_MIN
    )


def _resolve(
    store: PredictionShadowStore,
    decision_id: str,
    *,
    pnl: str = "1",
    baseline: str = "0",
    exit_reason: str = "TP",
) -> None:
    with store._connect() as connection:
        rows = connection.execute(
            "SELECT horizon_min,eligible_at_ms FROM prediction_outcomes WHERE decision_id=?",
            (decision_id,),
        ).fetchall()
        for horizon, eligible in rows:
            outcome = {
                "horizon_min": int(horizon),
                "buy_filled": exit_reason != "NO_TRADE",
                "tp_before_stop": True if exit_reason == "TP" else None,
                "net_pnl_quote": pnl,
                "mae_pct": "0",
                "time_to_fill_sec": 1 if exit_reason != "NO_TRADE" else None,
                "exit_reason": exit_reason,
                "resolved_at_ms": int(eligible),
            }
            baseline_outcome = dict(outcome)
            baseline_outcome["net_pnl_quote"] = baseline
            connection.execute(
                """UPDATE prediction_outcomes
                   SET resolved_at_ms=?,outcome_json=?,baseline_outcome_json=?,
                       terminal_reason='RESOLVED'
                   WHERE decision_id=? AND horizon_min=?""",
                (
                    int(eligible), json.dumps(outcome), json.dumps(baseline_outcome),
                    decision_id, int(horizon),
                ),
            )


def _record(
    store: PredictionShadowStore,
    variant,
    *,
    timestamp: int,
    experiment_id: str,
    role: str,
    regime: str = "RANGE",
) -> str:
    candidate_fp, baseline_fp = variant_fingerprints(
        variant,
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    )
    return store.record(
        kind=variant.kind,
        symbol="SOLUSDT",
        features=_features(timestamp, regime),
        plan=variant.plan,
        baseline_plan=variant.baseline_plan,
        predictions=_predictions(),
        algorithm_decision=variant.variant_id,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
        experiment_id=experiment_id,
        evidence_role=role,
        candidate_fingerprint=candidate_fp,
        baseline_fingerprint=baseline_fp,
    )


def _frozen(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    variants = _variants()
    snapshot = 59_999
    cohort = selection_experiment_id(SHADOW_GENERATION, "SOLUSDT")
    for variant in variants:
        decision_id = _record(
            store,
            variant,
            timestamp=snapshot,
            experiment_id=cohort,
            role="SELECTION",
        )
        _resolve(store, decision_id)
    frozen_at = evaluation_end_ms(snapshot, max(EXPERIMENT_HORIZONS_MIN)) + 1
    manifest = freeze_experiment(
        store,
        experiment_id="exp-v10-gap36",
        generation=SHADOW_GENERATION,
        symbol="SOLUSDT",
        selected_variant=variants[1],
        all_variants=variants,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
        selection_end_ts_ms=snapshot,
        product_version="2.20.191",
        source_commit="a" * 40,
        frozen_at_ms=frozen_at,
    )
    return store, variants, manifest


def test_selection_evidence_never_becomes_confirmation(tmp_path: Path):
    store, _variants_value, manifest = _frozen(tmp_path)

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert report["confirmation_progress"]["complete_decisions"] == 0
    assert report["first_gate_passed"] is False
    with store._connect() as connection:
        assert connection.execute(
            "SELECT DISTINCT evidence_role FROM prediction_decisions"
        ).fetchall() == [("SELECTION",)]


def test_pre_freeze_decision_settled_later_is_excluded(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    decision_id = _record(
        store,
        variants[1],
        timestamp=int(manifest["confirmation_start_ts_ms"]) - 1,
        experiment_id=manifest["experiment_id"],
        role="DIAGNOSTIC",
    )
    _resolve(store, decision_id)

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert report["confirmation_progress"]["complete_decisions"] == 0


def test_assignment_uses_only_selected_variant_after_boundary(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    timestamp = int(manifest["confirmation_start_ts_ms"])

    selected = evidence_assignment(
        store,
        generation=SHADOW_GENERATION,
        symbol="SOLUSDT",
        variant=variants[1],
        horizons_min=EXPERIMENT_HORIZONS_MIN,
        snapshot_ts_ms=timestamp,
    )
    other = evidence_assignment(
        store,
        generation=SHADOW_GENERATION,
        symbol="SOLUSDT",
        variant=variants[0],
        horizons_min=EXPERIMENT_HORIZONS_MIN,
        snapshot_ts_ms=timestamp,
    )

    assert selected == (manifest["experiment_id"], "CONFIRMATION")
    assert other == (manifest["experiment_id"], "DIAGNOSTIC")


@pytest.mark.parametrize(
    "changed",
    (
        lambda row: replace(row, entry_gap_bps=row.entry_gap_bps + D("1")),
        lambda row: replace(row, plan=replace(row.plan, entry_ttl_sec=7200)),
        lambda row: replace(row, regime_policy="RANGE"),
        lambda row: replace(row, model_rule="predict_distribution:v2"),
    ),
)
def test_semantic_changes_create_new_candidate_fingerprint(changed):
    variant = _variants()[1]
    original = variant_fingerprints(
        variant,
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    )[0]
    updated = variant_fingerprints(
        changed(variant),
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    )[0]

    assert updated != original


def test_horizon_baseline_and_criteria_changes_create_new_fingerprints():
    variant = _variants()[1]
    candidate, baseline = variant_fingerprints(
        variant,
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    )
    horizon_candidate, _ = variant_fingerprints(
        variant,
        generation=SHADOW_GENERATION,
        horizons_min=(90, 150),
    )
    criteria = dict(DEFAULT_CRITERIA)
    criteria["window_size_decisions"] = 30
    criteria_candidate, _ = variant_fingerprints(
        variant,
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
        criteria=criteria,
    )
    baseline_variant = replace(
        variant,
        baseline_plan=replace(variant.baseline_plan, fee_pct=D("0.001")),
    )
    _, changed_baseline = variant_fingerprints(
        baseline_variant,
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    )

    assert horizon_candidate != candidate
    assert criteria_candidate != candidate
    assert changed_baseline != baseline


def test_manifest_is_canonical_immutable_and_restart_safe(tmp_path: Path):
    store, _variants_value, manifest = _frozen(tmp_path)
    restarted = PredictionShadowStore(store.path)

    loaded = load_manifest(restarted, manifest["experiment_id"])

    assert canonical_json(json.loads(canonical_json(loaded["criteria"]))) == canonical_json(loaded["criteria"])
    assert loaded["candidate_fingerprint"] == manifest["candidate_fingerprint"]
    with restarted._connect() as connection, pytest.raises(
        sqlite3.IntegrityError, match="immutable"
    ):
        connection.execute(
            "UPDATE prediction_experiment_manifests SET selected_variant='changed'"
        )
    with pytest.raises(ValueError, match="already frozen"):
        freeze_experiment(
            restarted,
            experiment_id=manifest["experiment_id"],
            generation=SHADOW_GENERATION,
            symbol="SOLUSDT",
            selected_variant=_variants()[1],
            all_variants=_variants(),
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            selection_end_ts_ms=59_999,
            product_version="2.20.191",
            source_commit="a" * 40,
        )


def test_incomplete_selection_blocks_freeze(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    variants = _variants()
    cohort = selection_experiment_id(SHADOW_GENERATION, "SOLUSDT")
    for variant in variants:
        _record(store, variant, timestamp=59_999, experiment_id=cohort, role="SELECTION")

    with pytest.raises(ValueError, match="fully closed"):
        freeze_experiment(
            store,
            experiment_id="blocked",
            generation=SHADOW_GENERATION,
            symbol="SOLUSDT",
            selected_variant=variants[1],
            all_variants=variants,
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            selection_end_ts_ms=59_999,
            product_version="2.20.191",
            source_commit="a" * 40,
            frozen_at_ms=20_000_000,
        )


def test_asymmetric_selection_snapshots_block_freeze(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    variants = _variants()
    cohort = selection_experiment_id(SHADOW_GENERATION, "SOLUSDT")
    for variant in variants:
        decision_id = _record(
            store, variant, timestamp=59_999, experiment_id=cohort, role="SELECTION"
        )
        _resolve(store, decision_id)
    extra_id = _record(
        store,
        variants[0],
        timestamp=359_999,
        experiment_id=cohort,
        role="SELECTION",
    )
    _resolve(store, extra_id)

    with pytest.raises(ValueError, match="identical snapshots"):
        freeze_experiment(
            store,
            experiment_id="asymmetric-selection",
            generation=SHADOW_GENERATION,
            symbol="SOLUSDT",
            selected_variant=variants[1],
            all_variants=variants,
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            selection_end_ts_ms=359_999,
            product_version="2.20.192",
            source_commit="a" * 40,
            frozen_at_ms=20_000_000,
        )


def test_freeze_time_before_closed_selection_is_rejected(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    variants = _variants()
    cohort = selection_experiment_id(SHADOW_GENERATION, "SOLUSDT")
    for variant in variants:
        decision_id = _record(
            store, variant, timestamp=59_999, experiment_id=cohort, role="SELECTION"
        )
        _resolve(store, decision_id)

    with pytest.raises(ValueError, match="freeze time precedes"):
        freeze_experiment(
            store,
            experiment_id="bad-boundary",
            generation=SHADOW_GENERATION,
            symbol="SOLUSDT",
            selected_variant=variants[1],
            all_variants=variants,
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            selection_end_ts_ms=59_999,
            product_version="2.20.191",
            source_commit="a" * 40,
            frozen_at_ms=60_000,
        )


def test_missing_manifest_blocks_confirmation(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")

    report = confirmation_report(store, experiment_id="missing")

    assert report["confirmation_status"] == "BLOCKED"
    assert report["first_gate_passed"] is False
    assert report["apply_allowed"] is False


def test_incomplete_window_is_pending_and_cannot_pass(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    start = int(manifest["confirmation_start_ts_ms"])
    for index in range(11):
        decision_id = _record(
            store,
            variants[1],
            timestamp=start + index * 300_000,
            experiment_id=manifest["experiment_id"],
            role="CONFIRMATION",
        )
        _resolve(store, decision_id)

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert report["windows"][-1]["status"] == "PENDING"
    assert report["complete_windows"] == 0
    assert report["first_gate_passed"] is False


def test_horizons_do_not_inflate_independent_decisions(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    decision_id = _record(
        store,
        variants[1],
        timestamp=int(manifest["confirmation_start_ts_ms"]),
        experiment_id=manifest["experiment_id"],
        role="CONFIRMATION",
    )
    _resolve(store, decision_id)

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert report["confirmation_progress"]["complete_decisions"] == 1


def test_report_is_read_only_and_does_not_advance_lifecycle(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    decision_id = _record(
        store,
        variants[1],
        timestamp=int(manifest["confirmation_start_ts_ms"]),
        experiment_id=manifest["experiment_id"],
        role="CONFIRMATION",
    )
    _resolve(store, decision_id)

    first = confirmation_report(store, experiment_id=manifest["experiment_id"])
    second = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert first["experiment_lifecycle_status"] == "FROZEN"
    assert second["experiment_lifecycle_status"] == "FROZEN"
    with store._connect() as connection:
        transitions = connection.execute(
            "SELECT from_status,to_status FROM prediction_experiment_transitions"
        ).fetchall()
    assert transitions == [("SELECTION", "FROZEN")]


def test_unresolved_decision_stops_confirmation_prefix(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    start = int(manifest["confirmation_start_ts_ms"])
    for index in range(120):
        decision_id = _record(
            store,
            variants[1],
            timestamp=start + index * 300_000,
            experiment_id=manifest["experiment_id"],
            role="CONFIRMATION",
            regime=("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")[index % 4],
        )
        if index != 5:
            _resolve(store, decision_id)

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert report["confirmation_progress"]["complete_decisions"] == 5
    assert report["confirmation_progress"]["pending_decisions"] == 115
    assert report["complete_windows"] == 0
    assert "confirmation sequence contains an unresolved decision" in report[
        "blocking_reasons"
    ]


def test_finalize_rejects_a_stale_report_fingerprint(tmp_path: Path):
    store, _variants_value, manifest = _frozen(tmp_path)

    with pytest.raises(ValueError, match="report changed"):
        finalize_experiment(
            store,
            experiment_id=manifest["experiment_id"],
            expected_report_sha256="0" * 64,
        )


def test_full_independent_confirmation_can_pass_without_apply(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    start = int(manifest["confirmation_start_ts_ms"])
    regimes = ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
    for index in range(120):
        decision_id = _record(
            store,
            variants[1],
            timestamp=start + index * 300_000,
            experiment_id=manifest["experiment_id"],
            role="CONFIRMATION",
            regime=regimes[index % 4],
        )
        _resolve(store, decision_id)

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert report["complete_windows"] == 10
    assert report["positive_windows"] == 10
    complete_windows = [row for row in report["windows"] if row["status"] == "COMPLETE"]
    assert all(
        left["end_ts_ms"] < right["start_ts_ms"]
        for left, right in zip(complete_windows, complete_windows[1:])
    )
    assert report["confirmation_status"] == "READY_TO_FINALIZE"
    assert report["evaluation_passed"] is True
    assert report["first_gate_passed"] is False
    finalized = finalize_experiment(
        store,
        experiment_id=manifest["experiment_id"],
        expected_report_sha256=report["report_sha256"],
    )
    assert finalized["first_gate_passed"] is True
    assert finalized["eligible_for_second_gate_review"] is True
    assert finalized["promotion_eligible"] is True
    assert report["apply_allowed"] is False
    assert report["can_change_orders"] is False
    assert report["lookahead"] is False


def test_unstable_windows_fail_even_with_positive_total(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    start = int(manifest["confirmation_start_ts_ms"])
    regimes = ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
    for index in range(120):
        decision_id = _record(
            store,
            variants[1],
            timestamp=start + index * 300_000,
            experiment_id=manifest["experiment_id"],
            role="CONFIRMATION",
            regime=regimes[index % 4],
        )
        window = index // 12
        _resolve(store, decision_id, pnl="10" if window < 6 else "-1")

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert D(report["cumulative_pnl_quote"]) > 0
    assert report["negative_windows"] == 4
    assert report["first_gate_passed"] is False


def test_fingerprint_mismatch_blocks_confirmation(tmp_path: Path):
    store, variants, manifest = _frozen(tmp_path)
    decision_id = _record(
        store,
        variants[1],
        timestamp=int(manifest["confirmation_start_ts_ms"]),
        experiment_id=manifest["experiment_id"],
        role="CONFIRMATION",
    )
    _resolve(store, decision_id)
    with store._connect() as connection:
        connection.execute(
            "UPDATE prediction_decisions SET candidate_fingerprint=? WHERE decision_id=?",
            ("0" * 64, decision_id),
        )

    report = confirmation_report(store, experiment_id=manifest["experiment_id"])

    assert "confirmation fingerprint differs from frozen manifest" in report["blocking_reasons"]
    assert report["first_gate_passed"] is False


def test_old_schema_rows_migrate_to_legacy_without_confirmation(tmp_path: Path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE prediction_decisions(
                decision_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,
                kind TEXT NOT NULL,symbol TEXT NOT NULL,snapshot_ts_ms INTEGER NOT NULL,
                feature_json TEXT NOT NULL,plan_json TEXT NOT NULL,
                baseline_plan_json TEXT,prediction_json TEXT NOT NULL,
                algorithm_decision TEXT NOT NULL,created_at_ms INTEGER NOT NULL,
                UNIQUE(kind,symbol,snapshot_ts_ms,algorithm_decision));
            CREATE TABLE prediction_outcomes(
                decision_id TEXT NOT NULL,horizon_min INTEGER NOT NULL,
                eligible_at_ms INTEGER NOT NULL,resolved_at_ms INTEGER,
                outcome_json TEXT,baseline_outcome_json TEXT,
                PRIMARY KEY(decision_id,horizon_min));
            INSERT INTO prediction_decisions VALUES(
                'old',1,'EXPERIMENT_V8','SOLUSDT',1,'{}','{}','{}','[]','v8',1);
        """)

    store = PredictionShadowStore(database)
    PredictionShadowStore(database)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT evidence_role,experiment_id FROM prediction_decisions WHERE decision_id='old'"
        ).fetchone()

    assert row == ("LEGACY", None)


def test_rule_fingerprint_uses_relative_semantics_not_dynamic_price():
    first = _variants()[1]
    scaled = replace(
        first,
        plan=replace(
            first.plan,
            entry_price=first.plan.entry_price * D("2"),
            take_profit_price=first.plan.take_profit_price * D("2"),
            stop_price=first.plan.stop_price * D("2"),
        ),
        baseline_plan=replace(
            first.baseline_plan,
            entry_price=first.baseline_plan.entry_price * D("2"),
            take_profit_price=first.baseline_plan.take_profit_price * D("2"),
            stop_price=first.baseline_plan.stop_price * D("2"),
        ),
    )

    assert candidate_rule(
        first, generation=SHADOW_GENERATION, horizons_min=EXPERIMENT_HORIZONS_MIN
    ) == candidate_rule(
        scaled, generation=SHADOW_GENERATION, horizons_min=EXPERIMENT_HORIZONS_MIN
    )


def test_lifecycle_module_has_no_exchange_mutation_capability():
    source = Path(
        "ladder_dragon/strategy/prediction/experiment_lifecycle.py"
    ).read_text(encoding="utf-8")

    assert "place_order" not in source
    assert "cancel_order" not in source
    assert "signed_request" not in source
    assert "tools_market" not in source
