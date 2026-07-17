# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Минимальная трёхклассовая logistic regression без внешних ML-зависимостей."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

from ai_advisor import MarketContext


CLASSES = ("DOWN", "FLAT", "UP")


def context_vector(context: MarketContext) -> tuple[float, ...]:
    """Нормализованный фиксированный набор числовых рыночных признаков."""
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


class MulticlassLogisticRegime:
    """Детерминированное SGD-обучение softmax на локальной shadow-истории."""

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
