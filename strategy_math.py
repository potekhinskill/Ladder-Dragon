"""Чистые детерминированные расчёты, общие для торговых процессов.

Здесь намеренно нет сети, окружения, логирования и изменяемого состояния биржи.
Это позволяет тестировать изменения стратегии без запуска торговых процессов.
"""

from __future__ import annotations

from typing import Sequence
import time


class RegimeHysteresis:
    """Debounce режимов: смена допускается только после устойчивого сигнала."""
    def __init__(self, initial: str = "NEUTRAL", *, min_hold_sec: float = 300.0,
                 confirmations: int = 2) -> None:
        self.current = initial
        self.min_hold_sec = max(0.0, float(min_hold_sec))
        self.confirmations = max(1, int(confirmations))
        self._candidate = initial
        self._count = 0
        self._changed_at = 0.0

    def update(self, candidate: str, now: float | None = None) -> str:
        now = time.time() if now is None else float(now)
        candidate = str(candidate).upper()
        if candidate == self.current:
            self._candidate, self._count = candidate, 0
            return self.current
        if candidate != self._candidate:
            self._candidate, self._count = candidate, 1
        else:
            self._count += 1
        if self._count >= self.confirmations and now - self._changed_at >= self.min_hold_sec:
            self.current = candidate
            self._changed_at = now
            self._count = 0
        return self.current


class NumericHysteresis:
    """Дебаунс числовых параметров CAP/width, чтобы шум не менял план."""
    def __init__(self, initial: float, *, max_step: float = 0.10, confirmations: int = 2) -> None:
        self.value = float(initial)
        self.max_step = max(0.0, float(max_step))
        self.confirmations = max(1, int(confirmations))
        self._candidate = self.value
        self._count = 0

    def update(self, candidate: float) -> float:
        candidate = float(candidate)
        if abs(candidate - self.value) <= self.max_step * max(abs(self.value), 1e-12):
            self.value = candidate
            self._candidate, self._count = candidate, 0
            return self.value
        if abs(candidate - self._candidate) <= 1e-12:
            self._count += 1
        else:
            self._candidate, self._count = candidate, 1
        if self._count >= self.confirmations:
            self.value = candidate
            self._count = 0
        return self.value


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def ema_value(values: Sequence[float], period: int) -> float:
    if not values:
        return 0.0
    period = max(1, int(period))
    weight = 2.0 / (period + 1.0)
    result = float(values[0])
    for value in values[1:]:
        result = float(value) * weight + result * (1.0 - weight)
    return result


def ema_series(values: Sequence[float], length: int) -> list[float]:
    if length <= 1 or not values:
        return [float(value) for value in values]
    weight = 2.0 / (length + 1.0)
    current = (
        sum(float(value) for value in values[:length]) / float(length)
        if len(values) >= length
        else float(values[0])
    )
    result = [current]
    for value in values[1:]:
        current = float(value) * weight + current * (1.0 - weight)
        result.append(current)
    return result


def atr_from_klines(klines: Sequence[Sequence[object]], period: int = 14) -> float:
    if len(klines) < period + 2:
        return 0.0
    closed = klines[:-1]
    highs = [float(row[2]) for row in closed]
    lows = [float(row[3]) for row in closed]
    closes = [float(row[4]) for row in closed]
    true_ranges = [
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(closes))
    ]
    if len(true_ranges) < period:
        return 0.0
    return ema_value(true_ranges[-(period * 3):], period)


def adx_from_klines(klines: Sequence[Sequence[object]], length: int = 14) -> float:
    if not klines or len(klines) < length + 2:
        return 0.0
    highs = [float(row[2]) for row in klines]
    lows = [float(row[3]) for row in klines]
    closes = [float(row[4]) for row in klines]

    true_ranges: list[float] = []
    positive_dm: list[float] = []
    negative_dm: list[float] = []
    for index in range(1, len(klines)):
        up = highs[index] - highs[index - 1]
        down = lows[index - 1] - lows[index]
        true_ranges.append(max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        ))
        positive_dm.append(up if up > down and up > 0 else 0.0)
        negative_dm.append(down if down > up and down > 0 else 0.0)

    smoothed_tr = sum(true_ranges[:length])
    smoothed_positive = sum(positive_dm[:length])
    smoothed_negative = sum(negative_dm[:length])
    directional_indexes: list[float] = []
    epsilon = 1e-12
    for index in range(length, len(true_ranges)):
        smoothed_tr = smoothed_tr - smoothed_tr / length + true_ranges[index]
        smoothed_positive = smoothed_positive - smoothed_positive / length + positive_dm[index]
        smoothed_negative = smoothed_negative - smoothed_negative / length + negative_dm[index]
        positive_di = 100.0 * smoothed_positive / (smoothed_tr + epsilon)
        negative_di = 100.0 * smoothed_negative / (smoothed_tr + epsilon)
        directional_indexes.append(
            100.0 * abs(positive_di - negative_di) / (positive_di + negative_di + epsilon)
        )
    if not directional_indexes:
        return 0.0

    adx = (
        sum(directional_indexes[:length]) / float(length)
        if len(directional_indexes) >= length
        else directional_indexes[-1]
    )
    for index in range(length, len(directional_indexes)):
        adx = (adx * (length - 1) + directional_indexes[index]) / float(length)
    return float(adx)


def panic_triggered(
    now_price: float,
    ema20: float | None,
    atr: float | None,
    previous_close: float | None,
    drop_pct: float,
    atr_multiplier: float,
) -> bool:
    """Сработал ли хотя бы один триггер резкого движения рынка."""
    below_atr_band = (
        ema20 is not None
        and atr is not None
        and atr > 0
        and now_price <= ema20 - atr_multiplier * atr
    )
    abrupt_drop = (
        previous_close is not None
        and previous_close > 0
        and now_price / previous_close - 1.0 <= -abs(drop_pct)
    )
    return below_atr_band or abrupt_drop


def geometric_ladder(
    now_price: float,
    low_pct: float,
    down_pct: float,
    up_pct: float,
    density: int,
) -> list[float]:
    """Построить геометрические BUY/SELL-половины лестницы вокруг цены."""
    def levels(start_pct: float, end_pct: float) -> list[float]:
        if density <= 0:
            return []
        start = 1.0 + start_pct / 100.0
        end = 1.0 + end_pct / 100.0
        ratios = [start] if density == 1 else [
            start * ((end / start) ** (index / (density - 1)))
            for index in range(density)
        ]
        return [round(now_price * ratio, 8) for ratio in ratios]

    return levels(low_pct, down_pct) + levels(abs(low_pct), up_pct)


def split_ladder(now_price: float, ladder: Sequence[float]) -> tuple[list[float], list[float]]:
    """Сохранить историческое деление пополам; now_price оставлен для API."""
    del now_price
    midpoint = len(ladder) // 2
    return list(ladder[:midpoint]), list(ladder[midpoint:])


def shift_buy_levels(
    ladder_prices: Sequence[float],
    now_price: float,
    shift_pct: float,
) -> list[float]:
    if shift_pct <= 0:
        return list(ladder_prices)
    factor = 1.0 - clamp(float(shift_pct), 0.0, 0.95)
    return [
        max(0.0, price * factor) if price < now_price else price
        for price in ladder_prices
    ]
