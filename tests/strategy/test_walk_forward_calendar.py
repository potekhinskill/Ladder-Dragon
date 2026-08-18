# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify independent walk-forward training and calendar evidence.
"""Walk-forward calendar and independent training regressions."""

from dataclasses import replace
from decimal import Decimal

from ladder_dragon.strategy.prediction.models import PredictionOutcome, ResolvedSample
from ladder_dragon.strategy.prediction.approval import configuration_edge_p_value
from ladder_dragon.strategy.prediction.walk_forward import (
    evaluated_walk_forward_samples,
    walk_forward_prediction_report,
)
from ladder_dragon.strategy.prediction.statistical_design import (
    DEFAULT_STATISTICAL_DESIGN,
    REQUIRED_EVALUATION_SNAPSHOTS,
)


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
    assert gate["required_total_independent_samples"] == 112
    assert gate["minimum_calendar_duration_ms"] == (
        111 * 21_600_001 + 360 * 60_000
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
        last_timestamp + 102 * 21_600_001 + 360 * 60_000
    )


def test_configuration_hypothesis_excludes_training_outcomes():
    samples = _samples(61)
    samples = [
        row if index >= len(samples) - 2 else replace(
            row,
            outcome=PredictionOutcome(
                row.horizon_min, True, False, D("-999"), D("0"), 1,
                "STOP", row.snapshot_ts_ms + row.horizon_min * 60_000,
            ),
        )
        for index, row in enumerate(samples)
    ]
    evaluated = evaluated_walk_forward_samples(
        samples, required_horizons_min=(300, 360)
    )

    assert {row.snapshot_ts_ms for row in evaluated} == {
        60 * 21_600_001
    }
    assert configuration_edge_p_value(
        evaluated, required_horizons_min=(300, 360)
    ) == 0.5


def test_power_design_replaces_fixed_evaluation_volume():
    assert REQUIRED_EVALUATION_SNAPSHOTS == 52
    assert DEFAULT_STATISTICAL_DESIGN.as_dict() == {
        "method": "exact_one_sided_sign_test_bonferroni_v1",
        "family_alpha": 0.05,
        "target_power": 0.8,
        "minimum_win_probability": 0.72,
        "hypothesis_count": 5,
        "required_evaluation_snapshots": 52,
        "required_historical_training_snapshots": 30,
        "maximum_selection_duration_ms": 3_888_000_000,
        "maximum_confirmation_duration_ms": 3_888_000_000,
    }


def test_closed_history_satisfies_training_without_consuming_live_rows():
    report = walk_forward_prediction_report(
        _samples(5),
        historical_training_snapshots=30,
        historical_training_max_ts_ms=-1,
        as_of_ts_ms=4 * 21_600_001,
        required_horizons_min=(300, 360),
    )
    gate = report["gate"]

    assert gate["historical_training_independent_samples"] == 30
    assert gate["live_training_independent_samples"] == 0
    assert gate["evaluated_independent_samples"] == 5
    assert gate["required_total_independent_samples"] == 52
    assert all(row["train_max_ts_ms"] == -1 for row in report["evaluated"])


def test_selection_deadline_stops_an_unfinished_design():
    samples = _samples(2)
    deadline = DEFAULT_STATISTICAL_DESIGN.maximum_selection_duration_ms
    report = walk_forward_prediction_report(
        samples,
        historical_training_snapshots=30,
        historical_training_max_ts_ms=-1,
        as_of_ts_ms=deadline + 1,
        required_horizons_min=(300, 360),
    )

    assert report["gate"]["selection_deadline_expired"] is True
    assert "predeclared selection deadline expired" in report["gate"]["reasons"]
