from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from bin.prediction_experiment import _selection_variants
from ladder_dragon.strategy.prediction import (
    PredictionFeatures,
    PredictionShadowStore,
    TradePlan,
    predict_distribution,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    selection_experiment_id,
    variant_fingerprints,
)
from ladder_dragon.strategy.prediction.experiments import (
    EXPERIMENT_HORIZONS_MIN,
    SHADOW_GENERATION,
    build_shadow_variants,
    configured_entry_gap_bps,
)


D = Decimal


def test_configured_gap_rejects_unknown_semantics():
    with pytest.raises(ValueError, match="unavailable for generation"):
        configured_entry_gap_bps("v10_maker_ttl60_gap38", generation="v10")
    with pytest.raises(ValueError, match="unavailable for variant"):
        configured_entry_gap_bps("v11_maker_ttl60_gap99")
    assert configured_entry_gap_bps(
        "v11_maker_ttl60_gap42", generation="v11"
    ) == D("42")
    with pytest.raises(ValueError, match="requires a symbol"):
        configured_entry_gap_bps(
            "v12_maker_ttl60_gap46", generation="v12"
        )
    assert configured_entry_gap_bps(
        "v12_maker_ttl60_gap46", generation="v12", symbol="SOLUSDT"
    ) == D("46")
    assert configured_entry_gap_bps(
        "v12_maker_ttl60_gap22", generation="v12", symbol="ETHUSDT"
    ) == D("22")


def _features(snapshot: int, price: str) -> PredictionFeatures:
    return PredictionFeatures(
        snapshot_ts_ms=snapshot,
        last_closed_bar_ts_ms=snapshot,
        price=D(price),
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
        regime="RANGE",
    )


def test_selection_preview_uses_stable_configured_gap(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    baseline = TradePlan(
        entry_price=D("99.7"),
        take_profit_price=D("100.697"),
        stop_price=D("98.703"),
        notional_quote=D("10"),
        fee_pct=D("0.00075"),
        slippage_pct=D("0.0005"),
    )
    cohort = selection_experiment_id(SHADOW_GENERATION, "SOLUSDT")
    reconstructed = []
    for snapshot, market, rounded_entry in (
        (59_999, "100", D("99.5801")),
        (119_999, "101", D("100.5757")),
    ):
        features = _features(snapshot, market)
        configured = build_shadow_variants(
            market_price=D(market),
            baseline_plan=baseline,
            required_edge_pct=D("0.0096"),
            regime="RANGE",
        )[1]
        target_ratio = configured.plan.take_profit_price / configured.plan.entry_price
        stop_ratio = configured.plan.stop_price / configured.plan.entry_price
        rounded = replace(
            configured,
            plan=replace(
                configured.plan,
                entry_price=rounded_entry,
                take_profit_price=rounded_entry * target_ratio,
                stop_price=rounded_entry * stop_ratio,
            ),
        )
        candidate_fp, baseline_fp = variant_fingerprints(
            rounded,
            generation=SHADOW_GENERATION,
            horizons_min=EXPERIMENT_HORIZONS_MIN,
        )
        store.record(
            kind=rounded.kind,
            symbol="SOLUSDT",
            features=features,
            plan=rounded.plan,
            baseline_plan=baseline,
            predictions=predict_distribution(
                features,
                rounded.plan,
                [],
                horizons_min=EXPERIMENT_HORIZONS_MIN,
            ),
            algorithm_decision="stable selection preview regression",
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            experiment_id=cohort,
            evidence_role="SELECTION",
            candidate_fingerprint=candidate_fp,
            baseline_fingerprint=baseline_fp,
        )
        reconstructed.append(_selection_variants(
            store,
            generation=SHADOW_GENERATION,
            symbol="SOLUSDT",
            cutoff=snapshot,
        )[0])

    assert [row.entry_gap_bps for row in reconstructed] == [D("50"), D("50")]
    assert variant_fingerprints(
        reconstructed[0],
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    ) == variant_fingerprints(
        reconstructed[1],
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    )
