# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: provide transparent calibrated regime models without heavy dependencies.

"""Small deterministic statistical models suitable for Raspberry Pi SHADOW."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


CLASSES = ("DOWN", "FLAT", "UP")


@dataclass(frozen=True)
class ProbabilityPrediction:
    label: str
    probabilities: tuple[float, float, float]
    available: bool
    samples: int

    @property
    def confidence(self) -> float:
        return max(self.probabilities)


class PlattCalibrator:
    """Calibrate a binary raw score on a strictly separate historical window."""

    def __init__(self) -> None:
        self.slope = 0.0
        self.intercept = 0.0
        self.samples = 0

    def fit(
        self,
        rows: Iterable[tuple[float, bool]],
        *,
        epochs: int = 200,
        learning_rate: float = 0.03,
    ) -> None:
        examples = [(float(score), bool(label)) for score, label in rows]
        self.samples = len(examples)
        if not examples:
            return
        slope = 0.0
        intercept = 0.0
        for _ in range(epochs):
            slope_gradient = 0.0
            intercept_gradient = 0.0
            for score, expected in examples:
                bounded = max(-30.0, min(30.0, slope * score + intercept))
                probability = 1.0 / (1.0 + math.exp(-bounded))
                error = probability - float(expected)
                slope_gradient += error * score
                intercept_gradient += error
            scale = learning_rate / len(examples)
            slope -= scale * slope_gradient
            intercept -= scale * intercept_gradient
        self.slope = slope
        self.intercept = intercept

    def predict(self, score: float) -> float:
        if not self.samples:
            raise ValueError("calibrator has not been fitted")
        bounded = max(-30.0, min(30.0, self.slope * score + self.intercept))
        return 1.0 / (1.0 + math.exp(-bounded))


@dataclass(frozen=True)
class _Stump:
    feature_index: int
    threshold: float
    left_scores: tuple[float, float, float]
    right_scores: tuple[float, float, float]


class ShallowGradientBoostingRegime:
    """Multiclass gradient boosting with deterministic decision stumps.

    Stumps intentionally cap interaction complexity. The model is a transparent
    challenger, not an execution authority.
    """

    def __init__(self, *, estimators: int = 24, learning_rate: float = 0.12) -> None:
        if not 1 <= estimators <= 200:
            raise ValueError("estimators must be between 1 and 200")
        self.estimators = estimators
        self.learning_rate = learning_rate
        self.stumps: list[_Stump] = []
        self.samples = 0

    @staticmethod
    def _softmax(scores: Sequence[float]) -> tuple[float, float, float]:
        maximum = max(scores)
        values = [math.exp(value - maximum) for value in scores]
        total = sum(values)
        return tuple(value / total for value in values)  # type: ignore[return-value]

    def fit(self, rows: Iterable[tuple[Sequence[float], str]]) -> None:
        examples = [
            (tuple(float(value) for value in vector), CLASSES.index(label))
            for vector, label in rows if label in CLASSES
        ]
        self.samples = len(examples)
        self.stumps = []
        if not examples:
            return
        dimensions = len(examples[0][0])
        if dimensions == 0 or any(len(vector) != dimensions for vector, _ in examples):
            raise ValueError("training vectors must have one stable dimension")
        scores = [[0.0, 0.0, 0.0] for _ in examples]
        for _ in range(self.estimators):
            residuals = []
            for index, (_vector, expected) in enumerate(examples):
                probabilities = self._softmax(scores[index])
                residuals.append(tuple(
                    float(class_index == expected) - probabilities[class_index]
                    for class_index in range(3)
                ))
            best: tuple[float, _Stump] | None = None
            for feature_index in range(dimensions):
                values = sorted({vector[feature_index] for vector, _ in examples})
                if len(values) < 2:
                    continue
                candidates = [
                    (left + right) / 2.0
                    for left, right in zip(values, values[1:])
                ]
                # Bound CPU and model complexity on the Pi.
                if len(candidates) > 32:
                    step = max(1, len(candidates) // 32)
                    candidates = candidates[::step][:32]
                for threshold in candidates:
                    left_indices = [
                        index for index, (vector, _label) in enumerate(examples)
                        if vector[feature_index] <= threshold
                    ]
                    right_indices = [
                        index for index in range(len(examples))
                        if index not in set(left_indices)
                    ]
                    if not left_indices or not right_indices:
                        continue
                    left = tuple(
                        sum(residuals[index][class_index] for index in left_indices)
                        / len(left_indices)
                        for class_index in range(3)
                    )
                    right = tuple(
                        sum(residuals[index][class_index] for index in right_indices)
                        / len(right_indices)
                        for class_index in range(3)
                    )
                    error = sum(
                        sum(
                            (
                                residuals[index][class_index]
                                - (left if index in left_indices else right)[class_index]
                            ) ** 2
                            for class_index in range(3)
                        )
                        for index in range(len(examples))
                    )
                    stump = _Stump(feature_index, threshold, left, right)
                    if best is None or error < best[0]:
                        best = (error, stump)
            if best is None:
                break
            stump = best[1]
            self.stumps.append(stump)
            for index, (vector, _label) in enumerate(examples):
                addition = (
                    stump.left_scores
                    if vector[stump.feature_index] <= stump.threshold
                    else stump.right_scores
                )
                for class_index in range(3):
                    scores[index][class_index] += (
                        self.learning_rate * addition[class_index]
                    )

    def predict(
        self,
        vector: Sequence[float],
        *,
        min_samples: int = 60,
    ) -> ProbabilityPrediction:
        if self.samples < min_samples or not self.stumps:
            return ProbabilityPrediction("FLAT", (0.0, 1.0, 0.0), False, self.samples)
        scores = [0.0, 0.0, 0.0]
        values = tuple(float(value) for value in vector)
        for stump in self.stumps:
            if stump.feature_index >= len(values):
                raise ValueError("prediction vector dimension does not match model")
            addition = (
                stump.left_scores
                if values[stump.feature_index] <= stump.threshold
                else stump.right_scores
            )
            for class_index in range(3):
                scores[class_index] += self.learning_rate * addition[class_index]
        probabilities = self._softmax(scores)
        index = max(range(3), key=probabilities.__getitem__)
        return ProbabilityPrediction(
            CLASSES[index], probabilities, True, self.samples
        )


class ThreeStateRegimeHMM:
    """A small supervised three-state HMM for regime persistence."""

    def __init__(self, *, smoothing: float = 1.0) -> None:
        self.smoothing = float(smoothing)
        self.transitions = [[1.0 / 3.0] * 3 for _ in range(3)]
        self.means: list[list[float]] = [[], [], []]
        self.variances: list[list[float]] = [[], [], []]
        self.samples = 0

    def fit(self, rows: Sequence[tuple[Sequence[float], str]]) -> None:
        examples = [
            (tuple(float(value) for value in vector), CLASSES.index(label))
            for vector, label in rows if label in CLASSES
        ]
        self.samples = len(examples)
        if not examples:
            return
        dimensions = len(examples[0][0])
        counts = [[self.smoothing] * 3 for _ in range(3)]
        for (_left_vector, left), (_right_vector, right) in zip(examples, examples[1:]):
            counts[left][right] += 1.0
        self.transitions = [
            [value / sum(row) for value in row]
            for row in counts
        ]
        for state in range(3):
            state_rows = [vector for vector, label in examples if label == state]
            if not state_rows:
                self.means[state] = [0.0] * dimensions
                self.variances[state] = [1.0] * dimensions
                continue
            means = [
                sum(row[index] for row in state_rows) / len(state_rows)
                for index in range(dimensions)
            ]
            variances = [
                max(
                    1e-6,
                    sum((row[index] - means[index]) ** 2 for row in state_rows)
                    / len(state_rows),
                )
                for index in range(dimensions)
            ]
            self.means[state] = means
            self.variances[state] = variances

    def _emission_log_probability(self, vector: Sequence[float], state: int) -> float:
        return -0.5 * sum(
            math.log(2.0 * math.pi * variance)
            + (float(value) - mean) ** 2 / variance
            for value, mean, variance in zip(
                vector,
                self.means[state],
                self.variances[state],
            )
        )

    def predict(
        self,
        vector: Sequence[float],
        *,
        previous_probabilities: Sequence[float] = (1 / 3, 1 / 3, 1 / 3),
        min_samples: int = 60,
    ) -> ProbabilityPrediction:
        if self.samples < min_samples:
            return ProbabilityPrediction("FLAT", (0.0, 1.0, 0.0), False, self.samples)
        logs = []
        for state in range(3):
            prior = sum(
                float(previous_probabilities[previous])
                * self.transitions[previous][state]
                for previous in range(3)
            )
            logs.append(
                math.log(max(1e-12, prior))
                + self._emission_log_probability(vector, state)
            )
        maximum = max(logs)
        values = [math.exp(value - maximum) for value in logs]
        total = sum(values)
        probabilities = tuple(value / total for value in values)
        index = max(range(3), key=probabilities.__getitem__)
        return ProbabilityPrediction(
            CLASSES[index],
            probabilities,  # type: ignore[arg-type]
            True,
            self.samples,
        )
