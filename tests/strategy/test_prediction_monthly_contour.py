# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify sequence-safe monthly HMM evaluation.

from decimal import Decimal

import pytest

from ladder_dragon.strategy.prediction.advanced_features import (
    ExtendedRegimeFeatures,
)
from ladder_dragon.strategy.prediction.historical_dataset import (
    HistoricalRegimeSample,
)
from ladder_dragon.strategy.prediction import monthly_contour
from ladder_dragon.strategy.prediction.statistical_models import (
    ProbabilityPrediction,
)


D = Decimal
MONTH_MS = 30 * 24 * 60 * 60_000


def _features(timestamp: int, marker: str) -> ExtendedRegimeFeatures:
    value = D(marker)
    return ExtendedRegimeFeatures(
        snapshot_ts_ms=timestamp,
        realized_volatility_short=value,
        realized_volatility_long=D("0.01"),
        volatility_ratio=value,
        vwap_deviation_pct=value,
        vwap_slope_pct=value,
        hour_sin=D("0"),
        hour_cos=D("1"),
        weekday_sin=D("0"),
        weekday_cos=D("1"),
        agg_trade_imbalance=value,
        agg_trade_available=True,
        funding_rate=value,
        funding_available=True,
        open_interest_change_pct=value,
        open_interest_available=True,
    )


def _sample(
    symbol: str,
    snapshot: int,
    horizon: int,
    label: str,
    marker: str,
) -> HistoricalRegimeSample:
    return HistoricalRegimeSample(
        symbol=symbol,
        snapshot_ts_ms=snapshot,
        label_ts_ms=snapshot + 10,
        horizon_min=horizon,
        features=_features(snapshot, marker),
        realized_return=D("0"),
        label=label,
    )


def test_hmm_training_separates_symbol_and_horizon_transitions():
    rows = [
        _sample("SOLUSDT", 100, 1, "DOWN", "0.01"),
        _sample("SOLUSDT", 200, 1, "DOWN", "0.01"),
        _sample("SOLUSDT", 100, 5, "UP", "0.02"),
        _sample("SOLUSDT", 200, 5, "UP", "0.02"),
        _sample("ETHUSDT", 100, 1, "FLAT", "0.03"),
        _sample("ETHUSDT", 200, 1, "FLAT", "0.03"),
    ]

    models = monthly_contour._fit_hmm_sequences(rows)

    assert set(models) == {("SOLUSDT", 1), ("SOLUSDT", 5), ("ETHUSDT", 1)}
    assert {model.samples for model in models.values()} == {2}
    assert models[("SOLUSDT", 1)].transitions[0] == pytest.approx(
        [0.5, 0.25, 0.25]
    )
    assert models[("SOLUSDT", 5)].transitions[2] == pytest.approx(
        [0.25, 0.25, 0.5]
    )
    assert models[("ETHUSDT", 1)].transitions[1] == pytest.approx(
        [0.25, 0.5, 0.25]
    )


def test_hmm_previous_state_is_independent_for_each_horizon(monkeypatch):
    instances = []

    class RecordingHMM:
        def __init__(self):
            self.samples = 0
            self.calls = []
            instances.append(self)

        def fit(self, rows):
            self.samples = len(rows)
            self.marker = rows[0][0][0]

        def predict(self, vector, *, previous_probabilities, min_samples):
            self.calls.append(tuple(previous_probabilities))
            return ProbabilityPrediction("UP", (0.1, 0.2, 0.7), True, self.samples)

    class RecordingBoosting:
        def fit(self, rows):
            self.samples = len(rows)

        def predict(self, vector, *, min_samples):
            return ProbabilityPrediction("UP", (0.1, 0.2, 0.7), True, self.samples)

    monkeypatch.setattr(monthly_contour, "ThreeStateRegimeHMM", RecordingHMM)
    monkeypatch.setattr(
        monthly_contour,
        "ShallowGradientBoostingRegime",
        RecordingBoosting,
    )
    samples = [
        _sample("SOLUSDT", 100, 1, "UP", "0.01"),
        _sample("SOLUSDT", 100, 5, "DOWN", "0.02"),
        _sample("SOLUSDT", MONTH_MS + 100, 1, "UP", "0.01"),
        _sample("SOLUSDT", MONTH_MS + 100, 5, "DOWN", "0.02"),
        _sample("SOLUSDT", MONTH_MS + 200, 1, "UP", "0.01"),
    ]

    evaluated = monthly_contour._walk_forward_predictions(
        samples,
        cutoff_ts_ms=2 * MONTH_MS,
        min_train_samples=1,
    )

    fitted = [instance for instance in instances if instance.samples]
    assert len(evaluated) == 3
    assert len(fitted) == 2
    for instance in fitted:
        assert instance.calls[0] == pytest.approx((1 / 3, 1 / 3, 1 / 3))
    horizon_one = next(instance for instance in fitted if instance.marker == 0.01)
    assert horizon_one.calls[1] == pytest.approx((0.1, 0.2, 0.7))


def test_cold_hmm_sequence_excludes_both_model_scores():
    samples = [
        _sample("SOLUSDT", 100, 1, "UP", "0.01"),
        _sample("SOLUSDT", 200, 1, "UP", "0.01"),
        _sample("SOLUSDT", 100, 5, "DOWN", "0.02"),
        _sample("SOLUSDT", MONTH_MS + 100, 1, "UP", "0.01"),
        _sample("SOLUSDT", MONTH_MS + 100, 5, "DOWN", "0.02"),
    ]

    evaluated = monthly_contour._walk_forward_predictions(
        samples,
        cutoff_ts_ms=2 * MONTH_MS,
        min_train_samples=2,
    )

    assert [(row["symbol"], row["actual"]) for row in evaluated] == [
        ("SOLUSDT", "UP")
    ]
