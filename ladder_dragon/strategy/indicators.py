# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own named technical-indicator algorithms used by strategy consumers.
"""Explicit technical-indicator algorithms with stable candle boundaries."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence


def _rows(
    klines: Sequence[Sequence[object]], *, exclude_latest: bool
) -> Sequence[Sequence[object]]:
    return klines[:-1] if exclude_latest and klines else klines


def _float_true_ranges(
    klines: Sequence[Sequence[object]], *, exclude_latest: bool
) -> list[float]:
    rows = _rows(klines, exclude_latest=exclude_latest)
    if len(rows) < 2:
        return []
    highs = [float(row[2]) for row in rows]
    lows = [float(row[3]) for row in rows]
    closes = [float(row[4]) for row in rows]
    return [
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(rows))
    ]


def atr_wilder_from_klines(
    klines: Sequence[Sequence[object]],
    period: int = 14,
    *,
    exclude_latest: bool,
) -> float:
    """Return Wilder Average True Range for one explicit candle population."""
    period = max(1, int(period))
    rows = _rows(klines, exclude_latest=exclude_latest)
    if len(rows) < period + 1:
        return 0.0
    highs = [Decimal(str(row[2])) for row in rows]
    lows = [Decimal(str(row[3])) for row in rows]
    closes = [Decimal(str(row[4])) for row in rows]
    true_ranges = [
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(rows))
    ]
    if len(true_ranges) < period:
        return 0.0
    average = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    for true_range in true_ranges[period:]:
        average = (
            average * Decimal(period - 1) + true_range
        ) / Decimal(period)
    return float(average)


def atr_sma_from_klines(
    klines: Sequence[Sequence[object]],
    period: int | None = None,
    *,
    exclude_latest: bool,
) -> float:
    """Return simple-average true range without claiming Wilder semantics."""
    true_ranges = _float_true_ranges(
        klines, exclude_latest=exclude_latest
    )
    if period is not None:
        period = max(1, int(period))
        if len(true_ranges) < period:
            return 0.0
        true_ranges = true_ranges[-period:]
    return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0


def atr_ema_from_klines(
    klines: Sequence[Sequence[object]],
    period: int = 14,
    *,
    exclude_latest: bool,
    maximum_true_ranges: int | None = None,
) -> float:
    """Return exponential-average true range with the standard EMA weight."""
    period = max(1, int(period))
    true_ranges = _float_true_ranges(
        klines, exclude_latest=exclude_latest
    )
    if len(true_ranges) < period:
        return 0.0
    if maximum_true_ranges is not None:
        limit = max(period, int(maximum_true_ranges))
        true_ranges = true_ranges[-limit:]
    weight = 2.0 / (period + 1.0)
    average = true_ranges[0]
    for true_range in true_ranges[1:]:
        average = true_range * weight + average * (1.0 - weight)
    return average
