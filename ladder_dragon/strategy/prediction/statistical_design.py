# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preregister power, cohort, and deadline rules for SHADOW experiments.

"""Immutable statistical design for prediction experiments."""

from __future__ import annotations

from dataclasses import dataclass
from math import comb


EXPECTANCY_REGIMES = ("TREND_UP", "TREND_DOWN", "RANGE")
PANIC_REGIME = "PANIC"
DAY_MS = 24 * 60 * 60_000


@dataclass(frozen=True)
class StatisticalDesign:
    """One preregistered power and calendar contract."""

    family_alpha: float = 0.05
    target_power: float = 0.80
    minimum_win_probability: float = 0.72
    hypothesis_count: int = 5
    historical_training_snapshots: int = 30
    maximum_selection_duration_ms: int = 45 * DAY_MS
    maximum_confirmation_duration_ms: int = 45 * DAY_MS

    def required_evaluation_snapshots(self) -> int:
        """Return the exact sample size for the Holm-adjusted sign test."""
        if not 0 < self.family_alpha < 1:
            raise ValueError("family alpha must be between zero and one")
        if not 0 < self.target_power < 1:
            raise ValueError("target power must be between zero and one")
        if not 0.5 < self.minimum_win_probability < 1:
            raise ValueError("minimum win probability must exceed one half")
        if self.hypothesis_count <= 0:
            raise ValueError("hypothesis count must be positive")
        per_test_alpha = self.family_alpha / self.hypothesis_count
        for observations in range(1, 10_001):
            critical = next((
                wins for wins in range(observations + 1)
                if sum(
                    comb(observations, index)
                    for index in range(wins, observations + 1)
                ) / (2 ** observations) <= per_test_alpha
            ), None)
            if critical is None:
                continue
            power = sum(
                comb(observations, wins)
                * self.minimum_win_probability ** wins
                * (1 - self.minimum_win_probability) ** (observations - wins)
                for wins in range(critical, observations + 1)
            )
            if power >= self.target_power:
                return observations
        raise ValueError("power design exceeds the supported sample range")

    def as_dict(self) -> dict[str, object]:
        """Return values suitable for immutable manifests and status reports."""
        return {
            "method": "exact_one_sided_sign_test_bonferroni_v1",
            "family_alpha": self.family_alpha,
            "target_power": self.target_power,
            "minimum_win_probability": self.minimum_win_probability,
            "hypothesis_count": self.hypothesis_count,
            "required_evaluation_snapshots": self.required_evaluation_snapshots(),
            "required_historical_training_snapshots": (
                self.historical_training_snapshots
            ),
            "maximum_selection_duration_ms": self.maximum_selection_duration_ms,
            "maximum_confirmation_duration_ms": (
                self.maximum_confirmation_duration_ms
            ),
        }


DEFAULT_STATISTICAL_DESIGN = StatisticalDesign()
REQUIRED_EVALUATION_SNAPSHOTS = (
    DEFAULT_STATISTICAL_DESIGN.required_evaluation_snapshots()
)


__all__ = [
    "DAY_MS",
    "DEFAULT_STATISTICAL_DESIGN",
    "EXPECTANCY_REGIMES",
    "PANIC_REGIME",
    "REQUIRED_EVALUATION_SNAPSHOTS",
    "StatisticalDesign",
]
