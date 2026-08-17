from decimal import Decimal

import pytest

from ladder_dragon.strategy.prediction import PredictionOutcome, ResolvedSample
from ladder_dragon.strategy.prediction.approval import prediction_apply_gate
from ladder_dragon.strategy.prediction.confirmation_statistics import (
    validate_confirmation_criteria,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import DEFAULT_CRITERIA
from ladder_dragon.strategy.prediction.statistical_units import (
    non_overlapping_timestamps,
)


D = Decimal


def _sample(timestamp: int, horizon: int) -> ResolvedSample:
    return ResolvedSample(
        snapshot_ts_ms=timestamp,
        regime="RANGE",
        horizon_min=horizon,
        outcome=PredictionOutcome(
            horizon, True, True, D("1"), D("0"), 1, "TP",
            timestamp + horizon * 60_000,
        ),
        baseline_net_pnl_quote=D("0"),
    )


def test_five_minute_snapshots_become_360_minute_statistical_units():
    timestamps = range(0, 24 * 60 * 60_000, 5 * 60_000)

    selected = non_overlapping_timestamps(
        timestamps, horizons_min=(300, 360)
    )

    assert selected == (0, 21_900_000, 43_800_000, 65_700_000)
    assert all(right - left > 21_600_000 for left, right in zip(selected, selected[1:]))


def test_apply_gate_reports_raw_and_purged_counts_without_mutating_evidence():
    samples = [
        _sample(timestamp, horizon)
        for timestamp in range(0, 12 * 60 * 60_000, 5 * 60_000)
        for horizon in (300, 360)
    ]
    original = tuple(samples)

    report = prediction_apply_gate(
        samples, required_horizons_min=(300, 360)
    )

    assert report["raw_snapshot_samples"] == 144
    assert report["independent_samples"] == 2
    assert report["excluded_overlapping_snapshots"] == 142
    assert tuple(samples) == original
    assert report["approved"] is False


def test_impossible_confirmation_design_is_rejected_before_freeze():
    criteria = dict(DEFAULT_CRITERIA)
    criteria["min_regime_samples"] = 31

    with pytest.raises(ValueError, match="regime requirement exceeds"):
        validate_confirmation_criteria(
            criteria, required_horizons_min=(300, 360)
        )


def test_holm_requirements_must_be_reachable_by_predeclared_blocks():
    criteria = dict(DEFAULT_CRITERIA)
    criteria["required_complete_windows"] = 6
    criteria["window_size_decisions"] = 20
    criteria["minimum_positive_windows"] = 6

    with pytest.raises(ValueError, match="too few blocks"):
        validate_confirmation_criteria(
            criteria, required_horizons_min=(300, 360)
        )
