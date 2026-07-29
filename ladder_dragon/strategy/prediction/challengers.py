# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compare deterministic, statistical and LLM regime challengers equally.

"""Equal-window challenger comparison for SHADOW evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ChallengerObservation:
    snapshot_ts_ms: int
    resolved_at_ms: int
    actual_label: str
    realized_return: Decimal
    predictions: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.resolved_at_ms <= self.snapshot_ts_ms:
            raise ValueError("challenger outcome must follow its snapshot")
        if self.actual_label not in {"DOWN", "FLAT", "UP"}:
            raise ValueError("invalid actual challenger label")
        if any(
            label not in {"DOWN", "FLAT", "UP"}
            for label in self.predictions.values()
        ):
            raise ValueError("invalid challenger prediction label")
        if not self.realized_return.is_finite():
            raise ValueError("challenger return must be finite")


def challenger_comparison_report(
    observations: Sequence[ChallengerObservation],
    *,
    cutoff_ts_ms: int,
) -> dict[str, object]:
    """Score every challenger on exactly the same resolved observations."""
    rows = [
        row for row in observations if row.resolved_at_ms <= cutoff_ts_ms
    ]
    sources = sorted({
        source for row in rows for source in row.predictions
    })
    report = {}
    for source in sources:
        eligible = [row for row in rows if source in row.predictions]
        correct = sum(
            row.predictions[source] == row.actual_label for row in eligible
        )
        large_down = [
            row for row in eligible
            if row.actual_label == "DOWN" and abs(row.realized_return) >= Decimal("0.01")
        ]
        caught = sum(
            row.predictions[source] == "DOWN" for row in large_down
        )
        report[source] = {
            "samples": len(eligible),
            "correct": correct,
            "accuracy": (
                format(Decimal(correct) / Decimal(len(eligible)), "f")
                if eligible else None
            ),
            "large_down_caught": caught,
            "large_down_total": len(large_down),
        }
    return {
        "same_window": True,
        "cutoff_ts_ms": cutoff_ts_ms,
        "models": report,
    }
