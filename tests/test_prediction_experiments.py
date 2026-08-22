from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

from ladder_dragon.strategy.prediction import (
    PredictionBar,
    PredictionFeatures,
    PredictionOutcome,
    PredictionShadowStore,
    ResolvedSample,
    TradePlan,
    evaluate_plan,
    predict_distribution,
)
from ladder_dragon.strategy.prediction.approval import (
    configuration_edge_p_value,
    holm_configuration_correction,
)
from ladder_dragon.strategy.prediction.experiments import (
    build_shadow_variants,
    compatible_historical_kinds,
    record_shadow_variants,
    shadow_variant_report,
)
from ladder_dragon.strategy.prediction.statistical_evidence import (
    closed_historical_training_evidence,
)


D = Decimal


def _features(regime: str = "RANGE") -> PredictionFeatures:
    return PredictionFeatures(
        snapshot_ts_ms=59_999,
        last_closed_bar_ts_ms=59_999,
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


def _baseline() -> TradePlan:
    return TradePlan(
        entry_price=D("99.70"),
        take_profit_price=D("100.5973"),
        stop_price=D("98.703"),
        notional_quote=D("10"),
        fee_pct=D("0.00075"),
        slippage_pct=D("0.0005"),
    )


def test_variants_clear_fee_floor_and_change_one_named_dimension():
    baseline = _baseline()
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
        regime="TREND_DOWN",
    )

    assert {variant.variant_id for variant in variants} == {
        "v16_maker_ttl60_gap48",
        "v16_maker_ttl75_gap48",
        "v16_maker_ttl90_gap48",
    }
    for variant in variants:
        target_pct = variant.plan.take_profit_price / variant.plan.entry_price - D("1")
        assert target_pct > D("0.0096")
        assert variant.baseline_plan == baseline
        assert variant.maker_only is True
        assert variant.plan.slippage_pct == D("0")
    assert {item.plan.entry_ttl_sec for item in variants} == {
        3_600, 4_500, 5_400,
    }
    assert all(item.plan.entry_enabled for item in variants)
    assert all(item.plan.entry_price == D("99.5200") for item in variants)
    assert all(item.dimension == "maker_entry_ttl" for item in variants)


def test_parallel_variants_share_snapshot_and_explicit_baseline(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    features = _features()
    baseline = _baseline()
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
        regime=features.regime,
    )

    decision_ids = record_shadow_variants(
        store,
        symbol="SOLUSDT",
        features=features,
        variants=variants,
    )

    assert len(set(decision_ids)) == 3
    with store._connect() as connection:
        rows = connection.execute(
            "SELECT kind,snapshot_ts_ms,baseline_plan_json "
            "FROM prediction_decisions ORDER BY kind"
        ).fetchall()
    assert len(rows) == 3
    assert {row[1] for row in rows} == {features.snapshot_ts_ms}
    assert all(row[0].startswith("EXPERIMENT_") for row in rows)
    assert {
        json.loads(row[2])["entry_price"] for row in rows
    } == {"99.70"}
    with store._connect() as connection:
        horizons = connection.execute(
            "SELECT DISTINCT horizon_min FROM prediction_outcomes "
            "ORDER BY horizon_min"
        ).fetchall()
    assert horizons == [(300,), (360,)]


def test_entry_ttl_rejects_a_fill_observed_after_expiry():
    plan = TradePlan(
        entry_price=D("99"),
        take_profit_price=D("101"),
        stop_price=D("98"),
        notional_quote=D("10"),
        fee_pct=D("0"),
        slippage_pct=D("0"),
        entry_ttl_sec=300,
    )
    bars = []
    for index in range(15):
        open_time = 60_000 + index * 60_000
        bars.append(PredictionBar(
            open_time,
            open_time + 59_999,
            D("100"),
            D("100.5"),
            D("98") if index >= 5 else D("99.5"),
            D("100"),
            D("10"),
        ))

    outcome = evaluate_plan(
        bars,
        snapshot_ts_ms=59_999,
        horizon_min=15,
        plan=plan,
    )

    assert outcome is not None
    assert outcome.buy_filled is False
    assert outcome.exit_reason == "NO_FILL"


def test_regime_veto_is_an_explicit_no_trade_outcome():
    plan = TradePlan(
        entry_price=D("99"),
        take_profit_price=D("101"),
        stop_price=D("98"),
        notional_quote=D("10"),
        fee_pct=D("0"),
        slippage_pct=D("0"),
        entry_enabled=False,
    )
    bar = PredictionBar(
        60_000, 119_999, D("100"), D("102"), D("97"), D("101"), D("10")
    )

    outcome = evaluate_plan(
        [bar], snapshot_ts_ms=59_999, horizon_min=1, plan=plan
    )

    assert outcome is not None
    assert outcome.exit_reason == "NO_TRADE"
    assert outcome.net_pnl_quote == D("0")
    predictions = predict_distribution(_features("TREND_DOWN"), plan, [])
    assert all(item.probability_buy_fill == 0 for item in predictions)
    assert all(item.expected_net_pnl_quote == 0 for item in predictions)


def test_variant_report_never_enables_apply(tmp_path: Path, monkeypatch):
    from ladder_dragon.strategy.prediction import experiments

    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
    )
    monkeypatch.setattr(
        experiments,
        "walk_forward_prediction_report",
        lambda samples, **_kwargs: {
            "gate": {
                "approved": True,
                "reasons": [],
                "available_independent_samples": 180,
                "training_independent_samples": 60,
                "evaluated_independent_samples": 120,
                "required_total_independent_samples": 180,
                "minimum_calendar_duration_ms": 1_000,
                "estimated_ready_ts_ms": 2_000,
            },
            "lookahead": False,
        },
    )
    monkeypatch.setattr(
        experiments,
        "holm_configuration_correction",
        lambda p_values: {name: True for name in p_values},
    )

    report = shadow_variant_report(
        store,
        symbol="SOLUSDT",
        variants=variants,
        before_ts_ms=60_000,
    )

    assert report["mode"] == "SHADOW"
    assert report["generation"] == "v16"
    assert report["horizons_min"] == [300, 360]
    assert report["can_change_orders"] is False
    assert all(
        item["selection_gate_passed"] is True
        and item["promotion_eligible"] is False
        and item["apply_allowed"] is False
        for item in report["variants"].values()
    )
    assert report["confirmation_evidence"]["confirmation_status"] == "BLOCKED"
    assert report["first_gate_passed"] is False
    assert report["calendar_plan"]["selection_minimum_duration_ms"] == 1_000
    assert report["calendar_plan"]["confirmation_minimum_duration_ms"] > (
        report["calendar_plan"]["embargo_ms"]
    )
    assert report["calendar_plan"]["end_to_end_minimum_duration_ms"] == (
        report["calendar_plan"]["selection_minimum_duration_ms"]
        + report["calendar_plan"]["confirmation_minimum_duration_ms"]
    )
    maker = report["variants"]["v16_maker_ttl60_gap48"]
    assert maker["entry_order_type"] == "LIMIT_MAKER"
    assert maker["exit_order_type"] == "OCO"
    assert maker["take_profit_order_type"] == "LIMIT_MAKER"
    assert maker["stop_order_type"] == "STOP_LOSS_LIMIT"
    assert maker["execution_model_status"] == "NOT_IMPLEMENTED"
    assert all(
        item["entry_order_type"] == "LIMIT_MAKER"
        for item in report["variants"].values()
    )


def test_variant_report_separates_active_cohort_from_opportunity_cost(monkeypatch):
    from ladder_dragon.strategy.prediction import experiments

    active = PredictionOutcome(
        1, True, True, D("1"), D("0"), 1, "TP", 1
    )
    no_trade = replace(
        active,
        buy_filled=False,
        tp_before_stop=None,
        net_pnl_quote=D("0"),
        time_to_fill_sec=None,
        exit_reason="NO_TRADE",
    )
    samples = [
        ResolvedSample(1, "RANGE", 1, active, D("0")),
        ResolvedSample(2, "TREND_UP", 1, no_trade, D("2")),
    ]
    variant = next(
        item
        for item in build_shadow_variants(
            market_price=D("100"),
            baseline_plan=_baseline(),
            required_edge_pct=D("0.0096"),
            regime="RANGE",
        )
        if item.variant_id == "v16_maker_ttl60_gap48"
    )

    class Store:
        def resolved_samples(self, *args, **kwargs):
            return samples

        def outcome_status_counts(self, *args, **kwargs):
            return {}

    monkeypatch.setattr(
        experiments,
        "walk_forward_prediction_report",
        lambda rows, **_kwargs: {
            "gate": {
                "approved": True,
                "independent_samples": len(rows),
                "fill_rate": str(len(rows)),
            }
        },
    )
    monkeypatch.setattr(
        experiments,
        "holm_configuration_correction",
        lambda p_values: {name: True for name in p_values},
    )

    report = shadow_variant_report(
        Store(),
        symbol="SOLUSDT",
        variants=[variant],
        before_ts_ms=10,
    )["variants"][variant.variant_id]

    assert report["comparison_scope"] == "full_strategy_replacement"
    assert report["no_trade_opportunity_cost_included"] is True
    assert report["gate"]["independent_samples"] == 2
    assert report["active_cohort"]["samples"] == 1
    assert report["active_cohort"]["diagnostic_only"] is True


def test_variant_report_separates_future_work_from_backlog(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    features = _features()
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
    )
    record_shadow_variants(
        store,
        symbol="SOLUSDT",
        features=features,
        variants=variants,
    )
    future_features = replace(
        features,
        snapshot_ts_ms=120_000,
        last_closed_bar_ts_ms=120_000,
    )
    record_shadow_variants(
        store,
        symbol="SOLUSDT",
        features=future_features,
        variants=variants,
    )

    report = shadow_variant_report(
        store,
        symbol="SOLUSDT",
        variants=variants,
        before_ts_ms=60_000,
    )

    counts = report["variants"]["v16_maker_ttl60_gap48"]["outcomes"]
    assert counts == {
        "total": 2,
        "resolved": 0,
        "expired": 0,
        "future": 2,
        "settling": 0,
        "overdue": 0,
        "cohort_snapshots": 1,
        "first_snapshot_ts_ms": 59_999,
        "last_snapshot_ts_ms": 59_999,
    }
    assert report["selection_progress"] == {
        "age_sec": 0,
        "snapshots": 1,
        "resolved_outcomes": 0,
        "total_outcomes": 6,
    }


def test_configuration_holm_uses_distinct_candidate_hypotheses():
    winning = []
    mixed = []
    for index in range(10):
        positive = PredictionOutcome(
            1, True, True, D("1"), D("0"), 1, "TP", index + 1
        )
        alternating = replace(
            positive,
            net_pnl_quote=D("1") if index % 2 == 0 else D("-1"),
        )
        timestamp = index * (15 * 60_000 + 1)
        winning.append(ResolvedSample(timestamp, "RANGE", 1, positive, D("0")))
        mixed.append(ResolvedSample(timestamp, "RANGE", 1, alternating, D("0")))
    p_values = {
        "winning": configuration_edge_p_value(winning),
        "mixed": configuration_edge_p_value(mixed),
    }

    corrected = holm_configuration_correction(p_values)

    assert p_values["winning"] != p_values["mixed"]
    assert corrected == {"winning": True, "mixed": False}


def test_experiment_recording_is_bounded_to_five_minute_snapshots(
    tmp_path: Path, monkeypatch
):
    from ladder_dragon.supervision import prediction_shadow

    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    prediction_shadow._EXPERIMENT_LAST_RECORD.clear()
    prediction_shadow._EXPERIMENT_REPORT_CACHE.clear()
    clock = {"now": 1_000.0}
    monkeypatch.setattr(
        prediction_shadow.time, "monotonic", lambda: clock["now"]
    )
    baseline = _baseline()

    prediction_shadow.collect_shadow_experiments(
        store,
        symbol="ETHUSDT",
        features=_features(),
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
    )
    clock["now"] = 1_060.0
    prediction_shadow.collect_shadow_experiments(
        store,
        symbol="ETHUSDT",
        features=replace(_features(), snapshot_ts_ms=119_999),
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
    )
    assert store.summary("ETHUSDT")["decisions"] == 3

    clock["now"] = 1_301.0
    prediction_shadow.collect_shadow_experiments(
        store,
        symbol="ETHUSDT",
        features=replace(_features(), snapshot_ts_ms=179_999),
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
    )
    assert store.summary("ETHUSDT")["decisions"] == 6


def test_symbol_scopes_keep_active_generations_separate(
    tmp_path: Path, monkeypatch
):
    from ladder_dragon.supervision import prediction_shadow

    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    prediction_shadow._EXPERIMENT_LAST_RECORD.clear()
    prediction_shadow._EXPERIMENT_REPORT_CACHE.clear()
    monkeypatch.setattr(prediction_shadow.time, "monotonic", lambda: 1_000)

    sol = prediction_shadow.collect_shadow_experiments(
        store,
        symbol="SOLUSDT",
        features=_features(),
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
    )
    eth = prediction_shadow.collect_shadow_experiments(
        store,
        symbol="ETHUSDT",
        features=_features(),
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
    )
    btc = prediction_shadow.collect_shadow_experiments(
        store,
        symbol="BTCUSDT",
        features=_features(),
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
    )

    assert sol["generation"] == "v19"
    assert sol["lifecycle_status"] == "LIVE_CONFIRMATION"
    assert sol["lifecycle_mode"] == "PROMOTION"
    assert sol["variant_id"] == "v19_maker_ttl90_gap48"
    assert sol["execution_episode"]["status"] == "BLOCKED"
    assert eth["generation"] == "v15"
    assert eth["lifecycle_status"] == "SELECTION"
    assert eth["superseded_selection_generations"] == [
        "v11", "v12", "v13", "v14",
    ]
    assert set(eth["variants"]) == {
        "v15_maker_ttl60_gap20",
        "v15_maker_ttl60_gap21",
        "v15_maker_ttl60_gap22",
    }
    assert btc["generation"] == "v14"
    assert btc["lifecycle_status"] == "SELECTION"
    assert btc["superseded_selection_generations"] == ["v11", "v12", "v13"]
    assert set(btc["variants"]) == {
        "v14_maker_ttl60_gap8p4",
        "v14_maker_ttl60_gap9p4",
        "v14_maker_ttl60_gap10p3",
    }
    assert sol["can_change_orders"] is False
    assert eth["can_change_orders"] is False
    assert btc["can_change_orders"] is False
    assert sol["superseded_generations"] == [
        "v11", "v12", "v13", "v14", "v15", "v16",
        "v17", "v18",
    ]
    assert eth["superseded_reports"]["v11"]["generation"] == "v11"
    assert eth["superseded_reports"]["v12"]["generation"] == "v12"
    assert (
        eth["superseded_reports"]["v11"]["lifecycle_status"]
        == "SUPERSEDED"
    )
    assert (
        eth["superseded_reports"]["v12"]["lifecycle_status"]
        == "SUPERSEDED"
    )
    assert btc["superseded_reports"]["v11"]["generation"] == "v11"
    assert (
        btc["superseded_reports"]["v11"]["lifecycle_status"]
        == "SUPERSEDED"
    )


def test_selection_stops_recording_after_preregistered_deadline(
    tmp_path: Path, monkeypatch
):
    from ladder_dragon.supervision import prediction_shadow
    from ladder_dragon.strategy.prediction.statistical_design import DAY_MS

    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    prediction_shadow._EXPERIMENT_LAST_RECORD.clear()
    prediction_shadow._EXPERIMENT_REPORT_CACHE.clear()
    clock = {"now": 1_000.0}
    monkeypatch.setattr(
        prediction_shadow.time, "monotonic", lambda: clock["now"]
    )
    prediction_shadow.collect_shadow_experiments(
        store,
        symbol="ETHUSDT",
        features=_features(),
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
    )
    clock["now"] = 2_000.0
    report = prediction_shadow.collect_shadow_experiments(
        store,
        symbol="ETHUSDT",
        features=replace(
            _features(), snapshot_ts_ms=59_999 + 45 * DAY_MS + 1
        ),
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
    )

    assert store.summary("ETHUSDT")["decisions"] == 3
    assert report["recording_stopped_by_deadline"] is True


def test_v14_variants_do_not_depend_on_the_current_regime():
    baseline = _baseline()
    range_variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
        regime="RANGE",
    )
    down_variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
        regime="TREND_DOWN",
    )

    assert range_variants == down_variants
    assert len(range_variants) == 3
    assert all(item.plan.entry_enabled for item in range_variants)
    assert all(item.maker_only for item in range_variants)


def test_v14_holds_gap_constant_and_changes_only_ttl():
    baseline = replace(_baseline(), entry_price=D("99.20"))
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
        regime="RANGE",
    )

    ttl_variants = [
        item for item in variants
        if item.dimension == "maker_entry_ttl"
    ]
    assert len(ttl_variants) == 3
    assert {item.plan.entry_price for item in ttl_variants} == {D("99.52")}
    assert {item.plan.entry_ttl_sec for item in ttl_variants} == {
        3_600, 4_500, 5_400,
    }
    assert all(
        baseline.entry_price < item.plan.entry_price < D("100")
        for item in ttl_variants
    )


def test_v15_cold_start_uses_only_identical_historical_semantics():
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
        generation="v15",
        symbol="SOLUSDT",
    )
    ttl60 = next(row for row in variants if row.plan.entry_ttl_sec == 3_600)
    ttl75 = next(row for row in variants if row.plan.entry_ttl_sec == 4_500)

    assert compatible_historical_kinds(
        ttl60, generation="v15", symbol="SOLUSDT"
    ) == (
        "EXPERIMENT_V12_MAKER_TTL60_GAP48",
        "EXPERIMENT_V13_MAKER_TTL60_GAP48",
        "EXPERIMENT_V14_MAKER_TTL60_GAP48",
    )
    assert compatible_historical_kinds(
        ttl75, generation="v15", symbol="SOLUSDT"
    ) == ("EXPERIMENT_V14_MAKER_TTL75_GAP48",)


def test_v16_does_not_train_on_older_fee_or_exit_semantics():
    variant = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
        generation="v16",
        symbol="SOLUSDT",
    )[0]

    assert compatible_historical_kinds(
        variant, generation="v16", symbol="SOLUSDT"
    ) == ()


def test_empty_compatible_kind_set_cannot_admit_unrelated_training(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    evidence = closed_historical_training_evidence(
        store,
        "SOLUSDT",
        before_ts_ms=1_000_000,
        required_horizons_min=(300, 360),
        maximum_snapshots=30,
        kinds=(),
    )

    assert evidence.independent_snapshots == 0
    assert evidence.source_snapshots == 0


def test_superseded_generation_keeps_legacy_training_contract(
    tmp_path: Path, monkeypatch
):
    from ladder_dragon.strategy.prediction import experiments

    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
        generation="v14",
        symbol="SOLUSDT",
    )
    monkeypatch.setattr(
        experiments,
        "closed_historical_training_evidence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy generation used powered historical training")
        ),
    )

    report = shadow_variant_report(
        store,
        symbol="SOLUSDT",
        variants=variants,
        before_ts_ms=60_000,
        generation="v14",
        horizons_min=(300, 360),
    )

    assert all(
        row["required_total_independent_samples"] == 180
        for row in report["variants"].values()
    )


def test_btc_v12_uses_calibrated_gaps_without_changing_lifetime():
    variants = build_shadow_variants(
        market_price=D("100000"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
        generation="v12",
        symbol="BTCUSDT",
    )

    assert {item.variant_id for item in variants} == {
        "v12_maker_ttl60_gap8p4",
        "v12_maker_ttl60_gap9p4",
        "v12_maker_ttl60_gap10p3",
    }
    assert {item.entry_gap_bps for item in variants} == {
        D("8.4"), D("9.4"), D("10.3"),
    }
    assert {item.plan.entry_ttl_sec for item in variants} == {3_600}
    assert all(item.dimension == "maker_entry_gap" for item in variants)
    assert all(item.maker_only for item in variants)


def test_eth_v13_narrows_the_gap_without_changing_other_semantics():
    variants = build_shadow_variants(
        market_price=D("2000"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
        generation="v13",
        symbol="ETHUSDT",
    )

    assert {item.variant_id for item in variants} == {
        "v13_maker_ttl60_gap20",
        "v13_maker_ttl60_gap21",
        "v13_maker_ttl60_gap22",
    }
    assert {item.entry_gap_bps for item in variants} == {
        D("20"), D("21"), D("22"),
    }
    assert {item.plan.entry_ttl_sec for item in variants} == {3_600}
    assert all(item.dimension == "maker_entry_gap" for item in variants)
    assert all(item.maker_only for item in variants)


def test_v14_horizons_observe_recovery_after_a_late_fill():
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
    )
    bars = [
        PredictionBar(
            60_000 + index * 60_000,
            119_999 + index * 60_000,
            D("100"),
            D("102") if index == 249 else D("100"),
            D("99.52") if index == 59 else D("100"),
            D("100"),
            D("1"),
        )
        for index in range(360)
    ]

    outcome_120 = evaluate_plan(
        bars,
        snapshot_ts_ms=59_999,
        horizon_min=120,
        plan=variants[0].plan,
    )
    outcome_300 = evaluate_plan(
        bars,
        snapshot_ts_ms=59_999,
        horizon_min=300,
        plan=variants[0].plan,
    )
    outcome_360 = evaluate_plan(
        bars,
        snapshot_ts_ms=59_999,
        horizon_min=360,
        plan=variants[0].plan,
    )

    assert outcome_120 is not None and outcome_120.exit_reason == "HORIZON"
    assert outcome_300 is not None and outcome_300.exit_reason == "TP"
    assert outcome_360 is not None and outcome_360.exit_reason == "TP"
    assert outcome_300.time_to_fill_sec == 3_600


def test_reanchor_is_not_an_apply_candidate():
    variants = build_shadow_variants(
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=D("0.0096"),
        regime="RANGE",
    )

    assert all("REANCHOR" not in item.kind for item in variants)
    assert all(item.dimension != "reanchor" for item in variants)


def test_missing_authoritative_edge_records_no_candidate(tmp_path: Path):
    from ladder_dragon.supervision.prediction_shadow import (
        collect_shadow_experiments,
    )

    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    report = collect_shadow_experiments(
        store,
        symbol="SOLUSDT",
        features=_features(),
        market_price=D("100"),
        baseline_plan=_baseline(),
        required_edge_pct=None,
    )

    assert report["available"] is False
    assert report["can_change_orders"] is False
    assert store.summary("SOLUSDT")["decisions"] == 0


def test_experiment_plan_metadata_fails_closed():
    payload = json.dumps({
        "entry_price": "99",
        "take_profit_price": "101",
        "stop_price": "98",
        "notional_quote": "10",
        "fee_pct": "0",
        "slippage_pct": "0",
        "entry_enabled": "false",
    })

    try:
        PredictionShadowStore._plan(payload)
    except ValueError as exc:
        assert str(exc) == "entry_enabled must be boolean"
    else:
        raise AssertionError("invalid entry_enabled must fail closed")

    bad_ttl = json.loads(payload)
    bad_ttl["entry_enabled"] = True
    bad_ttl["entry_ttl_sec"] = "300"
    try:
        PredictionShadowStore._plan(json.dumps(bad_ttl))
    except ValueError as exc:
        assert str(exc) == "entry_ttl_sec must be an integer"
    else:
        raise AssertionError("non-integer entry TTL must fail closed")


def test_experiment_module_has_no_order_or_exchange_transport():
    source = (
        Path(__file__).parents[1]
        / "ladder_dragon/strategy/prediction/experiments.py"
    ).read_text(encoding="utf-8")

    assert "place_order" not in source
    assert "cancel_order" not in source
    assert "signed_request" not in source
    assert "trading_manager" not in source
