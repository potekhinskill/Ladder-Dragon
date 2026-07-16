"""Pure portfolio statistics used by risk checks and stress tests."""

from __future__ import annotations

from math import sqrt
from typing import Iterable, Mapping, Sequence


def log_returns(prices: Sequence[float]) -> list[float]:
    result: list[float] = []
    for previous, current in zip(prices, prices[1:]):
        if previous <= 0 or current <= 0:
            continue
        result.append(current / previous - 1.0)
    return result


def rolling_correlation(
    left: Sequence[float], right: Sequence[float], *, window: int = 48
) -> float:
    """Pearson correlation of recent returns; 0 means insufficient evidence."""
    values_left = log_returns(left)[-window:]
    values_right = log_returns(right)[-window:]
    size = min(len(values_left), len(values_right))
    if size < 3:
        return 0.0
    values_left = values_left[-size:]
    values_right = values_right[-size:]
    mean_left = sum(values_left) / size
    mean_right = sum(values_right) / size
    covariance = sum(
        (a - mean_left) * (b - mean_right)
        for a, b in zip(values_left, values_right)
    )
    variance_left = sum((a - mean_left) ** 2 for a in values_left)
    variance_right = sum((b - mean_right) ** 2 for b in values_right)
    denominator = sqrt(variance_left * variance_right)
    return covariance / denominator if denominator > 0 else 0.0


def correlated_symbols(
    histories: Mapping[str, Sequence[float]],
    *,
    threshold: float = 0.70,
    window: int = 48,
) -> set[str]:
    """Return symbols belonging to a positively correlated exposure cluster."""
    names = [str(name).upper() for name in histories]
    correlated: set[str] = set()
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            correlation = rolling_correlation(
                histories[left_name], histories[right_name], window=window
            )
            if correlation >= threshold:
                correlated.update((left_name, right_name))
    return correlated


def stress_exposure(exposure_usdt: float, shocks: Iterable[float]) -> list[float]:
    """Mark-to-market exposure after simultaneous percentage shocks."""
    return [exposure_usdt * (1.0 + float(shock)) for shock in shocks]
