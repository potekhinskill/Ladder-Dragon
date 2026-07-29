from decimal import Decimal

import pytest

from ladder_dragon.strategy.prediction.advanced_features import (
    ExtendedRegimeFeatures,
    TimedMarketValue,
    ablation_vectors,
    build_extended_features,
)
from ladder_dragon.strategy.prediction.decision_value import (
    DecisionValueObservation,
    classifier_decision_value_report,
)
from ladder_dragon.strategy.prediction.ensemble import (
    RegimeVote,
    conservative_regime_ensemble,
)
from ladder_dragon.strategy.prediction.historical_dataset import (
    HistoricalRegimeSample,
    build_historical_samples,
    expanding_walk_forward_splits,
)
from ladder_dragon.strategy.prediction.models import PredictionBar
from ladder_dragon.strategy.prediction.monthly_contour import (
    monthly_prediction_report,
)
from ladder_dragon.strategy.prediction.statistical_models import (
    PlattCalibrator,
    ShallowGradientBoostingRegime,
    ThreeStateRegimeHMM,
)


D = Decimal
MONTH_MS = 30 * 24 * 60 * 60_000


def _bars(count: int = 140) -> list[PredictionBar]:
    output = []
    for index in range(count):
        price = D("100") + D(str(index)) * D("0.1")
        output.append(PredictionBar(
            open_time_ms=index * 60_000,
            close_time_ms=index * 60_000 + 59_999,
            open=price - D("0.03"),
            high=price + D("0.08"),
            low=price - D("0.08"),
            close=price,
            volume=D("10") + D(str(index % 4)),
        ))
    return output


def _extended(timestamp: int, value: str = "0.01") -> ExtendedRegimeFeatures:
    number = D(value)
    return ExtendedRegimeFeatures(
        snapshot_ts_ms=timestamp,
        realized_volatility_short=abs(number),
        realized_volatility_long=D("0.01"),
        volatility_ratio=abs(number),
        vwap_deviation_pct=number,
        vwap_slope_pct=number,
        hour_sin=ZERO,
        hour_cos=D("1"),
        weekday_sin=ZERO,
        weekday_cos=D("1"),
        agg_trade_imbalance=number,
        agg_trade_available=True,
        funding_rate=number,
        funding_available=True,
        open_interest_change_pct=number,
        open_interest_available=True,
    )


ZERO = D("0")


def test_money_metric_rewards_avoided_loss_and_weights_large_down():
    report = classifier_decision_value_report([
        DecisionValueObservation(
            100, 200, "DOWN", D("-0.02"), D("-5"), False
        ),
        DecisionValueObservation(
            300, 400, "UP", D("0.01"), D("2"), True
        ),
    ])

    assert report["decision_value_quote"] == "5"
    assert report["large_down_capture"] == {
        "caught": 1,
        "total": 1,
        "rate": "1",
    }
    assert report["confusion"]["DOWN"]["DOWN"] == 1


def test_extended_features_reject_future_external_values_and_offer_ablations():
    bars = _bars(80)
    as_of = bars[-1].close_time_ms
    features = build_extended_features(
        bars,
        as_of_ms=as_of,
        agg_trade_imbalance=D("0.4"),
        funding=[
            TimedMarketValue(as_of - 1, D("0.001")),
            TimedMarketValue(as_of + 1, D("99")),
        ],
        open_interest=[
            TimedMarketValue(as_of - 6 * 60_000, D("100")),
            TimedMarketValue(as_of - 1, D("105")),
            TimedMarketValue(as_of + 1, D("999")),
        ],
    )

    assert features.funding_rate == D("0.001")
    assert features.open_interest_change_pct == D("0.05")
    assert features.volatility_ratio >= 0
    variants = ablation_vectors(features)
    assert set(variants) == {
        "full",
        "without_volatility",
        "without_vwap",
        "without_session",
        "without_microstructure",
    }
    assert len({len(vector) for vector in variants.values()}) == 1


def test_historical_multi_symbol_samples_never_train_on_unresolved_labels():
    samples = build_historical_samples({
        "SOLUSDT": _bars(),
        "ETHUSDT": _bars(),
    })
    assert {sample.symbol for sample in samples} == {"SOLUSDT", "ETHUSDT"}
    assert all(sample.label_ts_ms > sample.snapshot_ts_ms for sample in samples)

    splits = expanding_walk_forward_splits(samples, min_train_samples=10)
    assert splits
    assert all(
        max(row.label_ts_ms for row in train) < test.snapshot_ts_ms
        for train, test in splits
    )


def test_historical_dataset_rejects_a_missing_minute():
    bars = _bars()
    with pytest.raises(ValueError, match="contiguous closed minutes"):
        build_historical_samples({"SOLUSDT": bars[:70] + bars[71:]})


def test_transparent_models_train_and_calibrate_without_external_dependencies():
    rows = [
        ((-2.0, -1.0), "DOWN"),
        ((-1.5, -0.7), "DOWN"),
        ((0.0, 0.0), "FLAT"),
        ((0.1, -0.1), "FLAT"),
        ((1.5, 0.7), "UP"),
        ((2.0, 1.0), "UP"),
    ] * 12
    boosting = ShallowGradientBoostingRegime(estimators=12)
    boosting.fit(rows)
    prediction = boosting.predict((2.2, 1.1), min_samples=60)
    assert prediction.available is True
    assert prediction.label == "UP"

    hmm = ThreeStateRegimeHMM()
    hmm.fit(rows)
    hmm_prediction = hmm.predict((2.0, 1.0), min_samples=60)
    assert hmm_prediction.available is True
    assert hmm_prediction.label == "UP"

    calibrator = PlattCalibrator()
    calibrator.fit([(-2, False), (-1, False), (1, True), (2, True)])
    assert calibrator.predict(2) > calibrator.predict(-2)


def test_ensemble_can_only_preserve_or_reduce_baseline_risk():
    allowed = conservative_regime_ensemble(
        {
            "deterministic": RegimeVote("deterministic", "UP", D("0.8")),
            "statistical": RegimeVote("statistical", "UP", D("0.7")),
            "llm": RegimeVote("llm", "UP", D("0.9")),
        },
        baseline_buy_allowed=True,
        baseline_cap_scale=D("0.6"),
    )
    assert allowed.buy_allowed is True
    assert allowed.cap_scale == D("0.6")

    vetoed = conservative_regime_ensemble(
        {
            "deterministic": RegimeVote("deterministic", "UP", D("0.8")),
            "statistical": RegimeVote("statistical", "DOWN", D("0.7")),
        },
        baseline_buy_allowed=True,
    )
    assert vetoed.buy_allowed is False
    assert vetoed.cap_scale == 0

    baseline_block = conservative_regime_ensemble(
        {"llm": RegimeVote("llm", "UP", D("1"))},
        baseline_buy_allowed=False,
    )
    assert baseline_block.buy_allowed is False


def test_monthly_report_is_cutoff_bound_hash_bound_and_shadow_only():
    samples = []
    for index in range(150):
        snapshot = MONTH_MS + index * 60_000
        samples.append(HistoricalRegimeSample(
            symbol="SOLUSDT",
            snapshot_ts_ms=snapshot,
            label_ts_ms=snapshot + 60_000,
            horizon_min=1,
            features=_extended(snapshot, "-0.01" if index % 3 == 0 else "0.01"),
            realized_return=D("-0.01" if index % 3 == 0 else "0.01"),
            label="DOWN" if index % 3 == 0 else "UP",
        ))
    for index in range(12):
        snapshot = 2 * MONTH_MS + index * 60_000
        samples.append(HistoricalRegimeSample(
            symbol="SOLUSDT",
            snapshot_ts_ms=snapshot,
            label_ts_ms=snapshot + 60_000,
            horizon_min=1,
            features=_extended(snapshot, "0.01"),
            realized_return=D("0.01"),
            label="UP",
        ))
    values = [
        DecisionValueObservation(
            2 * MONTH_MS,
            2 * MONTH_MS + 60_000,
            "DOWN",
            D("-0.02"),
            D("-1"),
            False,
        )
    ]

    report = monthly_prediction_report(
        samples,
        values,
        cutoff_ts_ms=3 * MONTH_MS,
        min_train_samples=120,
    )

    assert report["status"] == "PASS"
    assert report["mode"] == "SHADOW"
    assert report["risk_expansion"] is False
    assert report["lookahead_detected"] is False
    assert len(report["report_sha256"]) == 64


def test_invalid_observation_and_stale_feature_inputs_fail_closed():
    with pytest.raises(ValueError):
        DecisionValueObservation(
            200, 100, "UP", D("0.1"), D("1"), True
        )
    with pytest.raises(ValueError):
        build_extended_features(_bars(20), as_of_ms=1_000_000)
