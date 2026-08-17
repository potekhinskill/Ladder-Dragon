# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify independent walk-forward training and calendar evidence.
"""Walk-forward calendar and independent training regressions."""

from decimal import Decimal

from ladder_dragon.strategy.prediction.models import PredictionOutcome, ResolvedSample
from ladder_dragon.strategy.prediction.walk_forward import walk_forward_prediction_report


D = Decimal


def _samples(count: int) -> list[ResolvedSample]:
    output = []
    spacing = 21_600_001
    regimes = ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
    for index in range(count):
        timestamp = index * spacing
        for horizon in (300, 360):
            output.append(ResolvedSample(
                timestamp,
                regimes[index % len(regimes)],
                horizon,
                PredictionOutcome(
                    horizon, True, True, D("1"), D("0"), 1, "TP",
                    timestamp + horizon * 60_000,
                ),
                D("0"),
            ))
    return output


def test_training_threshold_counts_snapshots_instead_of_horizon_rows():
    report = walk_forward_prediction_report(
        _samples(65),
        min_train_independent_snapshots=60,
        required_horizons_min=(300, 360),
    )
    gate = report["gate"]

    assert gate["available_independent_samples"] == 65
    assert gate["training_independent_samples"] == 60
    assert gate["evaluated_independent_samples"] == 5
    assert gate["required_total_independent_samples"] == 180
    assert gate["minimum_calendar_duration_ms"] == (
        179 * 21_600_001 + 360 * 60_000
    )


def test_readiness_timestamp_includes_remaining_units_and_final_outcome():
    report = walk_forward_prediction_report(
        _samples(10),
        min_train_independent_snapshots=60,
        required_horizons_min=(300, 360),
    )
    gate = report["gate"]
    last_timestamp = 9 * 21_600_001

    assert gate["estimated_ready_ts_ms"] == (
        last_timestamp + 170 * 21_600_001 + 360 * 60_000
    )
