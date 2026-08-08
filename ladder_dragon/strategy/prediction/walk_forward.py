# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run chronological walk-forward prediction evaluation.

"""Chronological evaluation that trains only on earlier decision timestamps."""

from __future__ import annotations

from typing import Sequence

from ladder_dragon.strategy.prediction.approval import prediction_apply_gate
from ladder_dragon.strategy.prediction.models import ResolvedSample


def walk_forward_prediction_report(
    samples: Sequence[ResolvedSample],
    *,
    min_train_samples: int = 60,
) -> dict[str, object]:
    """Evaluate chronologically; a sample can train only later timestamps."""
    ordered = sorted(samples, key=lambda item: (item.snapshot_ts_ms, item.horizon_min))
    evaluated = []
    eligible_samples: list[ResolvedSample] = []
    prior_samples = 0
    prior_timestamp: int | None = None
    index = 0
    while index < len(ordered):
        timestamp = ordered[index].snapshot_ts_ms
        end = index
        while end < len(ordered) and ordered[end].snapshot_ts_ms == timestamp:
            end += 1
        current = ordered[index:end]
        if prior_samples >= min_train_samples and prior_timestamp is not None:
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
        prior_samples += len(current)
        prior_timestamp = timestamp
        index = end
    return {
        "schema_version": 1,
        "method": "expanding-window-walk-forward",
        "lookahead": False,
        "evaluated": evaluated,
        # The approval cohort must match the reported walk-forward cohort.
        # Cold-start rows have no valid training history and cannot affect APPLY.
        "gate": prediction_apply_gate(eligible_samples),
    }

__all__ = ["walk_forward_prediction_report"]
