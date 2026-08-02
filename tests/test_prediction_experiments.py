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
    dynamic_entry_gap_pct,
    record_shadow_variants,
    shadow_variant_report,
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
        "v2_range_only",
        "v2_tp_100",
        "v2_tp_105",
        "v2_tp_110",
        "v2_maker_only",
        "v2_buy_gap_5bps",
        "v2_buy_gap_8bps",
        "v2_buy_gap_10bps",
        "v2_ttl_3m",
        "v2_ttl_5m",
        "v2_ttl_8m",
        "v2_a_range_ttl5_maker_tp100_gap5",
        "v2_b_range_ttl5_maker_tp105_gap8",
        "v2_c_range_ttl5_maker_tp110_gap10",
        "v2_d_range_ttl8_maker_tp105_dynamic",
    }
    for variant in variants:
        target_pct = variant.plan.take_profit_price / variant.plan.entry_price - D("1")
        assert target_pct > D("0.0096")
        assert variant.baseline_plan == baseline
    by_id = {variant.variant_id: variant for variant in variants}
    assert by_id["v2_buy_gap_5bps"].plan.entry_price == D("99.9500")
    assert by_id["v2_buy_gap_8bps"].plan.entry_price == D("99.9200")
    assert by_id["v2_buy_gap_10bps"].plan.entry_price == D("99.9000")
    assert by_id["v2_ttl_3m"].plan.entry_ttl_sec == 180
    assert by_id["v2_ttl_5m"].plan.entry_ttl_sec == 300
    assert by_id["v2_ttl_8m"].plan.entry_ttl_sec == 480
    assert by_id["v2_range_only"].plan.entry_enabled is False
    assert by_id["v2_maker_only"].maker_only is True
    assert by_id["v2_maker_only"].plan.slippage_pct == D("0")
    assert by_id["v2_tp_100"].plan.take_profit_price == D("100.69700")
    assert by_id["v2_tp_105"].plan.take_profit_price == D("100.746850")
    assert by_id["v2_tp_110"].plan.take_profit_price == D("100.79670")
    combined = by_id["v2_b_range_ttl5_maker_tp105_gap8"]
    assert combined.dimension == "combined_range_execution"
    assert combined.plan.entry_price == D("99.9200")
    assert combined.plan.entry_ttl_sec == 300
    assert combined.plan.entry_enabled is False
    assert combined.plan.slippage_pct == D("0")
    assert combined.maker_only is True
    assert combined.plan.take_profit_price == D("100.9691600")
    dynamic = by_id["v2_d_range_ttl8_maker_tp105_dynamic"]
    assert dynamic.plan.entry_price == D("99.9500")
    assert dynamic.plan.entry_ttl_sec == 480


def test_dynamic_gap_is_decimal_and_bounded():
    assert dynamic_entry_gap_pct(
        spread_bps=D("1"), atr_pct=D("0.003")
    ) == D("0.00085")
    assert dynamic_entry_gap_pct(
        spread_bps=D("0"), atr_pct=D("0")
    ) == D("0.0005")
    assert dynamic_entry_gap_pct(
        spread_bps=D("20"), atr_pct=D("0.02")
    ) == D("0.0015")


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

    assert len(set(decision_ids)) == 15
    with store._connect() as connection:
        rows = connection.execute(
            "SELECT kind,snapshot_ts_ms,baseline_plan_json "
            "FROM prediction_decisions ORDER BY kind"
        ).fetchall()
    assert len(rows) == 15
    assert {row[1] for row in rows} == {features.snapshot_ts_ms}
    assert all(row[0].startswith("EXPERIMENT_") for row in rows)
    assert {
        json.loads(row[2])["entry_price"] for row in rows
    } == {"99.70"}


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
        lambda samples: {
            "gate": {"approved": True, "reasons": []},
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
    assert report["generation"] == "v2"
    assert report["can_change_orders"] is False
    assert all(
        item["promotion_eligible"] is True and item["apply_allowed"] is False
        for item in report["variants"].values()
    )
    maker = report["variants"]["v2_maker_only"]
    assert maker["entry_order_type"] == "LIMIT_MAKER"
    assert maker["exit_order_type"] == "LIMIT_MAKER"
    assert report["variants"]["v2_range_only"]["entry_order_type"] == "BASELINE"


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

    report = shadow_variant_report(
        store,
        symbol="SOLUSDT",
        variants=variants,
        before_ts_ms=60_000,
    )

    counts = report["variants"]["v2_tp_100"]["outcomes"]
    assert counts == {
        "total": 3,
        "resolved": 0,
        "expired": 0,
        "future": 3,
        "settling": 0,
        "overdue": 0,
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
        winning.append(ResolvedSample(index, "RANGE", 1, positive, D("0")))
        mixed.append(ResolvedSample(index, "RANGE", 1, alternating, D("0")))
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
        symbol="SOLUSDT",
        features=_features(),
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
    )
    clock["now"] = 1_060.0
    prediction_shadow.collect_shadow_experiments(
        store,
        symbol="SOLUSDT",
        features=replace(_features(), snapshot_ts_ms=119_999),
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
    )
    assert store.summary("SOLUSDT")["decisions"] == 15

    clock["now"] = 1_301.0
    prediction_shadow.collect_shadow_experiments(
        store,
        symbol="SOLUSDT",
        features=replace(_features(), snapshot_ts_ms=179_999),
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.0096"),
    )
    assert store.summary("SOLUSDT")["decisions"] == 30


def test_combined_variants_trade_only_in_range():
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

    range_combined = [
        item for item in range_variants
        if item.dimension == "combined_range_execution"
    ]
    down_combined = [
        item for item in down_variants
        if item.dimension == "combined_range_execution"
    ]
    assert len(range_combined) == len(down_combined) == 4
    assert all(item.plan.entry_enabled for item in range_combined)
    assert all(not item.plan.entry_enabled for item in down_combined)
    assert all(item.maker_only for item in range_combined + down_combined)


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
