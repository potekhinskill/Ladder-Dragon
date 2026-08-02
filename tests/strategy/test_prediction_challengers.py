# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify equal-sample comparison of prediction challengers.

from decimal import Decimal

from ladder_dragon.strategy.prediction.challengers import (
    ChallengerObservation,
    challenger_comparison_report,
)


def _observation(
    snapshot: int,
    actual: str,
    predictions: dict[str, str],
    *,
    realized_return: str = "0.001",
) -> ChallengerObservation:
    return ChallengerObservation(
        snapshot_ts_ms=snapshot,
        resolved_at_ms=snapshot + 10,
        actual_label=actual,
        realized_return=Decimal(realized_return),
        predictions=predictions,
    )


def test_challengers_use_one_full_coverage_cohort():
    observations = [
        _observation(100, "UP", {"rules": "UP", "llm": "DOWN"}),
        _observation(200, "DOWN", {"rules": "DOWN"}, realized_return="-0.02"),
        _observation(300, "UP", {"llm": "UP"}),
    ]

    report = challenger_comparison_report(observations, cutoff_ts_ms=1_000)

    assert report["same_window"] is True
    assert report["resolved_observations"] == 3
    assert report["common_observations"] == 1
    assert report["common_coverage"] == "0.3333333333333333333333333333"
    assert report["models"]["rules"] == {
        "samples": 1,
        "available_observations": 2,
        "correct": 1,
        "accuracy": "1",
        "large_down_caught": 0,
        "large_down_total": 0,
    }
    assert report["models"]["llm"]["samples"] == 1
    assert report["models"]["llm"]["available_observations"] == 2
    assert report["models"]["llm"]["accuracy"] == "0"


def test_challenger_cutoff_excludes_future_availability():
    observations = [
        _observation(100, "DOWN", {"rules": "DOWN", "llm": "DOWN"}),
        ChallengerObservation(
            snapshot_ts_ms=200,
            resolved_at_ms=2_000,
            actual_label="UP",
            realized_return=Decimal("0.01"),
            predictions={"future_only": "UP"},
        ),
    ]

    report = challenger_comparison_report(observations, cutoff_ts_ms=1_000)

    assert set(report["models"]) == {"llm", "rules"}
    assert report["resolved_observations"] == 1
    assert report["common_observations"] == 1
    assert report["common_coverage"] == "1"


def test_empty_challenger_report_has_no_claimed_coverage():
    report = challenger_comparison_report([], cutoff_ts_ms=1_000)

    assert report["models"] == {}
    assert report["resolved_observations"] == 0
    assert report["common_observations"] == 0
    assert report["common_coverage"] is None
