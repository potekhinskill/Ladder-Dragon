# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run chronological walk-forward prediction evaluation.

"""Chronological evaluation that trains only on earlier decision timestamps."""

from __future__ import annotations

from typing import Sequence

from ladder_dragon.strategy.prediction.approval import (
    prediction_apply_gate,
    regime_reachability_report,
)
from ladder_dragon.strategy.prediction.models import ResolvedSample
from ladder_dragon.strategy.prediction.statistical_units import (
    non_overlapping_timestamps,
    outcome_spacing_ms,
)
from ladder_dragon.strategy.prediction.statistical_design import (
    DEFAULT_STATISTICAL_DESIGN,
    REQUIRED_EVALUATION_SNAPSHOTS,
)


def evaluated_walk_forward_samples(
    samples: Sequence[ResolvedSample],
    *,
    min_train_independent_snapshots: int = 60,
    historical_training_snapshots: int = 0,
    required_horizons_min: Sequence[int] = (1, 5, 15),
) -> tuple[ResolvedSample, ...]:
    """Return the exact post-training cohort used by all approval tests."""
    if min_train_independent_snapshots < 0 or historical_training_snapshots < 0:
        raise ValueError("minimum training snapshots must be non-negative")
    live_training_required = max(
        0, min_train_independent_snapshots - historical_training_snapshots
    )
    horizons = tuple(int(value) for value in required_horizons_min)
    ordered = sorted(samples, key=lambda item: (item.snapshot_ts_ms, item.horizon_min))
    grouped_timestamps = {item.snapshot_ts_ms for item in ordered}
    retained = set(non_overlapping_timestamps(
        grouped_timestamps, horizons_min=horizons
    ))
    ordered = [item for item in ordered if item.snapshot_ts_ms in retained]
    eligible_samples: list[ResolvedSample] = []
    prior_snapshots = 0
    prior_timestamp: int | None = None
    index = 0
    while index < len(ordered):
        timestamp = ordered[index].snapshot_ts_ms
        end = index
        while end < len(ordered) and ordered[end].snapshot_ts_ms == timestamp:
            end += 1
        current = ordered[index:end]
        if (
            prior_snapshots >= live_training_required
            and (prior_timestamp is not None or live_training_required == 0)
        ):
            for sample in current:
                eligible_samples.append(sample)
        prior_snapshots += 1
        prior_timestamp = timestamp
        index = end
    return tuple(eligible_samples)


def walk_forward_prediction_report(
    samples: Sequence[ResolvedSample],
    *,
    min_train_independent_snapshots: int = (
        DEFAULT_STATISTICAL_DESIGN.historical_training_snapshots
    ),
    historical_training_snapshots: int = 0,
    historical_training_max_ts_ms: int | None = None,
    required_evaluation_snapshots: int = REQUIRED_EVALUATION_SNAPSHOTS,
    as_of_ts_ms: int | None = None,
    required_horizons_min: Sequence[int] = (1, 5, 15),
) -> dict[str, object]:
    """Evaluate chronologically; a sample can train only later timestamps."""
    horizons = tuple(int(value) for value in required_horizons_min)
    if historical_training_snapshots < 0:
        raise ValueError("historical training snapshots must be non-negative")
    if historical_training_snapshots and historical_training_max_ts_ms is None:
        raise ValueError("historical training cutoff is required")
    if required_evaluation_snapshots <= 0:
        raise ValueError("required evaluation snapshots must be positive")
    live_training_required = max(
        0, min_train_independent_snapshots - historical_training_snapshots
    )
    eligible_samples = list(evaluated_walk_forward_samples(
        samples,
        min_train_independent_snapshots=min_train_independent_snapshots,
        historical_training_snapshots=historical_training_snapshots,
        required_horizons_min=horizons,
    ))
    retained = non_overlapping_timestamps(
        {item.snapshot_ts_ms for item in samples}, horizons_min=horizons
    )
    if (
        historical_training_max_ts_ms is not None
        and retained
        and historical_training_max_ts_ms >= retained[0]
    ):
        raise ValueError("historical training must precede live evaluation")
    prior_by_timestamp = {
        timestamp: retained[index - 1]
        for index, timestamp in enumerate(retained)
        if index >= live_training_required and index > 0
    }
    if historical_training_max_ts_ms is not None and live_training_required == 0:
        prior_by_timestamp.update({
            timestamp: historical_training_max_ts_ms
            for timestamp in retained
        })
    evaluated = [
        {
                    "snapshot_ts_ms": sample.snapshot_ts_ms,
                    "horizon_min": sample.horizon_min,
                    "train_max_ts_ms": prior_by_timestamp[sample.snapshot_ts_ms],
                    "actual_net_pnl_quote": format(
                        sample.outcome.net_pnl_quote, "f"
                    ),
                    "baseline_net_pnl_quote": format(
                        sample.baseline_net_pnl_quote, "f"
                    ),
        }
        for sample in eligible_samples
    ]
    gate = prediction_apply_gate(
        eligible_samples,
        min_independent_samples=required_evaluation_snapshots,
        required_horizons_min=horizons,
    )
    reachability = regime_reachability_report(
        samples,
        required_horizons_min=horizons,
        minimum_per_regime=8,
    )
    if reachability["practically_reachable"] is False:
        reasons = list(gate["reasons"])
        reasons.append("projected regime coverage exceeds maximum duration")
        gate["reasons"] = list(dict.fromkeys(reasons))
        gate["approved"] = False
        gate["mode"] = "SHADOW"
    available = len(retained)
    live_training = min(available, live_training_required)
    credited_historical = min(
        historical_training_snapshots, min_train_independent_snapshots
    )
    training = credited_historical + live_training
    evaluated_count = max(0, available - live_training)
    required_evaluation = required_evaluation_snapshots
    required_total = live_training_required + required_evaluation
    spacing = outcome_spacing_ms(horizons)
    full_duration = (
        max(0, required_total - 1) * spacing + max(horizons) * 60_000
    )
    estimated_ready = None
    if retained:
        estimated_ready = (
            max(retained)
            + max(0, required_total - available) * spacing
            + max(horizons) * 60_000
        )
    selection_started_ms = min(retained) if retained else None
    selection_deadline_ms = (
        selection_started_ms
        + DEFAULT_STATISTICAL_DESIGN.maximum_selection_duration_ms
        if selection_started_ms is not None else None
    )
    expired = bool(
        selection_deadline_ms is not None
        and as_of_ts_ms is not None
        and as_of_ts_ms > selection_deadline_ms
        and not bool(gate.get("approved"))
    )
    waiting_reason = (
        "selection deadline expired"
        if expired else
        "independent cold-start training is incomplete"
        if training < min_train_independent_snapshots else
        "live independent evaluation is incomplete"
        if evaluated_count < required_evaluation else
        "statistical criteria are not met"
        if not bool(gate.get("approved")) else
        "selection gate passed"
    )
    if expired:
        reasons = list(gate.get("reasons", []))
        reasons.append("predeclared selection deadline expired")
        gate["reasons"] = list(dict.fromkeys(reasons))
        gate["approved"] = False
        gate["mode"] = "SHADOW"
    gate.update({
        "available_independent_samples": available,
        "training_independent_samples": training,
        "historical_training_independent_samples": credited_historical,
        "live_training_independent_samples": live_training,
        "required_training_independent_samples": min_train_independent_snapshots,
        "evaluated_independent_samples": evaluated_count,
        "required_total_independent_samples": required_total,
        "evaluation_minimum_calendar_duration_ms": gate.get(
            "minimum_calendar_duration_ms", 0
        ),
        "minimum_calendar_duration_ms": full_duration,
        "estimated_ready_ts_ms": estimated_ready,
        "estimated_ready_days": (
            max(0, estimated_ready - as_of_ts_ms) / 86_400_000
            if estimated_ready is not None and as_of_ts_ms is not None else None
        ),
        "readiness_reason": waiting_reason,
        "selection_deadline_ts_ms": selection_deadline_ms,
        "selection_deadline_expired": expired,
        "sign_test_power": DEFAULT_STATISTICAL_DESIGN.as_dict(),
        "regime_reachability": reachability,
    })
    return {
        "schema_version": 1,
        "method": "expanding-window-walk-forward",
        "lookahead": False,
        "evaluated": evaluated,
        # The approval cohort must match the reported walk-forward cohort.
        # Cold-start rows have no valid training history and cannot affect APPLY.
        "gate": gate,
    }

__all__ = ["evaluated_walk_forward_samples", "walk_forward_prediction_report"]
