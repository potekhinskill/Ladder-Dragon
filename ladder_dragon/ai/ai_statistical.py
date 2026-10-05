# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the ai statistical component of the ai layer.
"""Ladder Dragon ai statistical support."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Iterable, Sequence

from ladder_dragon.ai.ai_advisor import MarketContext


CLASSES = ("DOWN", "FLAT", "UP")


def context_vector(context: MarketContext) -> tuple[float, ...]:
    """Handle context vector."""
    raw = (
        context.return_15m / .01,
        context.return_1h / .02,
        context.return_4h / .05,
        context.return_24h / .10,
        context.ema_gap_pct / .01,
        context.ema_slope / .001,
        (context.adx - 20) / 20,
        context.atr_pct / .03,
        context.orderbook_imbalance_top20,
        (context.volume_ratio_1h - 1) / 2,
    )
    return tuple(max(-3.0, min(3.0, float(value))) for value in raw)


def return_label(value: float, threshold: float = .001) -> str:
    if value > threshold:
        return "UP"
    if value < -threshold:
        return "DOWN"
    return "FLAT"


@dataclass(frozen=True)
class StatisticalPrediction:
    mode: str
    confidence: float
    samples: int
    available: bool
    calibrated: bool = False


class MulticlassLogisticRegime:
    """Represent MulticlassLogisticRegime."""

    def __init__(self, dimensions: int = 10) -> None:
        self.weights = [[0.0] * (dimensions + 1) for _ in CLASSES]
        self.samples = 0

    @staticmethod
    def _softmax(scores: Sequence[float]) -> list[float]:
        maximum = max(scores)
        values = [math.exp(score - maximum) for score in scores]
        total = sum(values)
        return [value / total for value in values]

    def fit(
        self,
        examples: Iterable[tuple[Sequence[float], str]],
        *,
        epochs: int = 80,
        learning_rate: float = .03,
        l2: float = .001,
    ) -> None:
        rows = [
            (tuple(float(value) for value in vector), CLASSES.index(label))
            for vector, label in examples if label in CLASSES
        ]
        self.samples = len(rows)
        for _ in range(epochs):
            for vector, expected in rows:
                features = (1.0, *vector)
                probabilities = self._softmax([
                    sum(weight * value for weight, value in zip(row, features))
                    for row in self.weights
                ])
                for class_index, row in enumerate(self.weights):
                    error = probabilities[class_index] - int(class_index == expected)
                    for index, value in enumerate(features):
                        penalty = 0.0 if index == 0 else l2 * row[index]
                        row[index] -= learning_rate * (error * value + penalty)

    def predict(
        self,
        vector: Sequence[float],
        *,
        min_samples: int = 60,
    ) -> StatisticalPrediction:
        if self.samples < min_samples:
            return StatisticalPrediction("FLAT", 0.0, self.samples, False)
        features = (1.0, *(float(value) for value in vector))
        probabilities = self._softmax([
            sum(weight * value for weight, value in zip(row, features))
            for row in self.weights
        ])
        index = max(range(len(CLASSES)), key=probabilities.__getitem__)
        return StatisticalPrediction(
            CLASSES[index], probabilities[index], self.samples, True
        )


@lru_cache(maxsize=2)
def _cached_regime_weights(training):
    """Retain two exact training prefixes, with immutable weights only.

    Hexadecimal keys preserve float identity, including signed zero. No
    prediction, calibration outcome, or execution permission is cached.
    This process-local cache disappears on restart; fit parameters are fixed.
    """
    model = MulticlassLogisticRegime()
    model.fit([(tuple(float.fromhex(value) for value in vector), label)
               for vector, label in training])
    return tuple(tuple(row) for row in model.weights), model.samples


def _fit_regime(model, training):
    """Reuse bounded finite inputs only; preserve the original fallback fit."""
    if len(training) > 2000 or any(len(vector) != 10 for vector, _ in training):
        model.fit(training)
        return
    normalized = [(tuple(float(value) for value in vector), label)
                  for vector, label in training if label in CLASSES]
    if any(not math.isfinite(value) for vector, _ in normalized for value in vector):
        model.fit(training)
        return
    key = tuple((tuple(value.hex() for value in vector), label)
                for vector, label in normalized)
    weights, model.samples = _cached_regime_weights(key)
    # Never expose the shared cached object to a mutable model instance.
    model.weights = [list(row) for row in weights]


def calibrated_logistic_prediction(
    examples: Sequence[tuple[Sequence[float], str]],
    vector: Sequence[float],
    *,
    min_samples: int = 60,
    min_calibration_samples: int = 20,
) -> StatisticalPrediction:
    """Fit chronologically and calibrate confidence on a later holdout."""
    from ladder_dragon.strategy.prediction.statistical_models import PlattCalibrator

    split = max(1, int(len(examples) * 0.8))
    training = examples[:split]
    calibration = examples[split:]
    model = MulticlassLogisticRegime()
    _fit_regime(model, training)
    raw = model.predict(vector, min_samples=min_samples)
    if not raw.available or len(calibration) < min_calibration_samples:
        return raw
    calibration_rows = []
    for calibration_vector, expected in calibration:
        prediction = model.predict(calibration_vector, min_samples=min_samples)
        if prediction.available:
            calibration_rows.append(
                (prediction.confidence, prediction.mode == expected)
            )
    if len(calibration_rows) < min_calibration_samples:
        return raw
    calibrator = PlattCalibrator()
    calibrator.fit(calibration_rows)
    return StatisticalPrediction(
        mode=raw.mode,
        confidence=calibrator.predict(raw.confidence),
        samples=len(examples),
        available=True,
        calibrated=True,
    )
