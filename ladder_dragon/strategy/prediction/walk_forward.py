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


def walk_forward_prediction_report(
    samples: Sequence[ResolvedSample],
    *,
    min_train_independent_snapshots: int = 60,
    required_horizons_min: Sequence[int] = (1, 5, 15),
) -> dict[str, object]:
    """Evaluate chronologically; a sample can train only later timestamps."""
    if min_train_independent_snapshots < 0:
        raise ValueError("minimum training snapshots must be non-negative")
    horizons = tuple(int(value) for value in required_horizons_min)
    ordered = sorted(samples, key=lambda item: (item.snapshot_ts_ms, item.horizon_min))
    grouped_timestamps = {item.snapshot_ts_ms for item in ordered}
    retained = set(non_overlapping_timestamps(
        grouped_timestamps, horizons_min=horizons
    ))
    ordered = [item for item in ordered if item.snapshot_ts_ms in retained]
    evaluated = []
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
            prior_snapshots >= min_train_independent_snapshots
            and prior_timestamp is not None
        ):
            for sample in current:
                eligible_samples.append(sample)
                evaluated.append({
                    "snapshot_ts_ms": sample.snapshot_ts_ms,
                    "horizon_min": sample.horizon_min,
                    "train_max_ts_ms": prior_timestamp,
                    "actual_net_pnl_quote": format(
                        sample.outcome.net_pnl_quote, "f"
                    ),
                    "baseline_net_pnl_quote": format(
                        sample.baseline_net_pnl_quote, "f"
                    ),
                })
        prior_snapshots += 1
        prior_timestamp = timestamp
        index = end
    gate = prediction_apply_gate(
        eligible_samples, required_horizons_min=horizons
    )
    reachability = regime_reachability_report(
        ordered,
        required_horizons_min=horizons,
        minimum_per_regime=20,
    )
    if reachability["practically_reachable"] is False:
        reasons = list(gate["reasons"])
        reasons.append("projected regime coverage exceeds maximum duration")
        gate["reasons"] = list(dict.fromkeys(reasons))
        gate["approved"] = False
        gate["mode"] = "SHADOW"
    available = len(retained)
    training = min(available, min_train_independent_snapshots)
    evaluated_count = max(0, available - training)
    required_evaluation = int(
        gate.get("required_evaluation_independent_samples", 120)
    )
    required_total = min_train_independent_snapshots + required_evaluation
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
    gate.update({
        "available_independent_samples": available,
        "training_independent_samples": training,
        "required_training_independent_samples": min_train_independent_snapshots,
        "evaluated_independent_samples": evaluated_count,
        "required_total_independent_samples": required_total,
        "evaluation_minimum_calendar_duration_ms": gate.get(
            "minimum_calendar_duration_ms", 0
        ),
        "minimum_calendar_duration_ms": full_duration,
        "estimated_ready_ts_ms": estimated_ready,
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

__all__ = ["walk_forward_prediction_report"]
