# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: calculate deterministic multi-symbol market scenarios from closed candles.
"""Pure SHADOW market scenario calculations without execution authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence


D = Decimal
ZERO = D("0")
ONE = D("1")
SUPPORTED_TIMEFRAMES = ("1h", "4h", "1d", "1w", "1M")
MINIMUM_BARS = 60
ENGINE_VERSION = "market-scenario-v1"


@dataclass(frozen=True)
class ScenarioBar:
    """Represent one authoritative closed market candle."""

    open_time_ms: int
    close_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class ScenarioAnalysis:
    """Describe one deterministic scenario snapshot."""

    schema_version: int
    engine_version: str
    symbol: str
    timeframe: str
    as_of_open_ms: int
    as_of_close_ms: int
    current_price: Decimal
    range_low: Decimal
    range_high: Decimal
    fibonacci_382: Decimal
    fibonacci_500: Decimal
    fibonacci_618: Decimal
    trend_bps_per_bar: Decimal
    momentum_20: Decimal
    volatility_20: Decimal
    primary_scenario: str
    bullish_weight: Decimal
    range_weight: Decimal
    bearish_weight: Decimal
    entry_condition: str
    invalidation_level: Decimal
    target_level: Decimal
    shadow_action: str
    probability_status: str
    mode: str = "SHADOW"
    apply_allowed: bool = False
    can_change_orders: bool = False

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe payload with exact decimal strings."""
        payload = asdict(self)
        for key, value in tuple(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = format(value, "f")
        return payload


def _finite(value: Decimal, name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def validate_bars(bars: Sequence[ScenarioBar], *, now_ms: int) -> tuple[ScenarioBar, ...]:
    """Reject open, unordered, malformed, or insufficient candle evidence."""
    if len(bars) < MINIMUM_BARS:
        raise ValueError(f"at least {MINIMUM_BARS} closed bars are required")
    ordered = tuple(bars)
    previous_open = -1
    for bar in ordered:
        values = tuple(
            _finite(value, name)
            for name, value in (
                ("open", bar.open), ("high", bar.high), ("low", bar.low),
                ("close", bar.close), ("volume", bar.volume),
            )
        )
        if bar.open_time_ms <= previous_open or bar.close_time_ms < bar.open_time_ms:
            raise ValueError("bars must be strictly chronological")
        if bar.close_time_ms >= now_ms:
            raise ValueError("open candles are forbidden")
        if min(values[:4]) <= ZERO or values[4] < ZERO:
            raise ValueError("bar prices must be positive and volume non-negative")
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            raise ValueError("bar OHLC values are inconsistent")
        previous_open = bar.open_time_ms
    return ordered


def _linear_trend_bps(closes: Sequence[Decimal]) -> Decimal:
    count = D(len(closes))
    mean_x = (count - ONE) / D("2")
    mean_y = sum(closes, ZERO) / count
    denominator = sum((D(index) - mean_x) ** 2 for index in range(len(closes)))
    if denominator == ZERO or mean_y == ZERO:
        return ZERO
    numerator = sum(
        (D(index) - mean_x) * (value - mean_y)
        for index, value in enumerate(closes)
    )
    return numerator / denominator / mean_y * D("10000")


def _mean_absolute_return(closes: Sequence[Decimal]) -> Decimal:
    returns = [
        abs(current / previous - ONE)
        for previous, current in zip(closes, closes[1:])
        if previous > ZERO
    ]
    return sum(returns, ZERO) / D(len(returns)) if returns else ZERO


def _weights(score: int) -> tuple[Decimal, Decimal, Decimal]:
    bounded = max(-3, min(3, score))
    bullish = D(3 + bounded)
    bearish = D(3 - bounded)
    ranging = D(3 - abs(bounded)) * D("2")
    total = bullish + bearish + ranging
    return bullish / total, ranging / total, bearish / total


def analyze_scenarios(
    symbol: str,
    timeframe: str,
    bars: Sequence[ScenarioBar],
    *,
    now_ms: int,
) -> ScenarioAnalysis:
    """Calculate levels and scenario weights from closed candles only."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol or not normalized_symbol.isalnum():
        raise ValueError("symbol must contain only uppercase letters and digits")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError("unsupported market analysis timeframe")
    ordered = validate_bars(bars, now_ms=now_ms)
    window = ordered[-MINIMUM_BARS:]
    closes = [bar.close for bar in window]
    recent = closes[-20:]
    low = min(bar.low for bar in window)
    high = max(bar.high for bar in window)
    span = high - low
    if span <= ZERO:
        raise ValueError("market analysis range must be positive")
    current = closes[-1]
    trend = _linear_trend_bps(recent)
    momentum = current / closes[-21] - ONE
    volatility = _mean_absolute_return(closes[-21:])
    midpoint = low + span * D("0.5")
    score = (
        (1 if trend > ZERO else -1 if trend < ZERO else 0)
        + (1 if momentum > ZERO else -1 if momentum < ZERO else 0)
        + (1 if current > midpoint else -1 if current < midpoint else 0)
    )
    bullish, ranging, bearish = _weights(score)
    if score >= 2:
        primary = "BULLISH"
        action = "LONG"
        entry = "closed price remains above the 0.500 retracement"
        invalidation = high - span * D("0.618")
        target = high
    elif score <= -2:
        primary = "BEARISH"
        action = "CASH"
        entry = "closed price remains below the 0.500 retracement"
        invalidation = high - span * D("0.382")
        target = low
    else:
        primary = "RANGE"
        action = "CASH"
        entry = "closed price remains between the 0.618 and 0.382 retracements"
        invalidation = low
        target = high
    return ScenarioAnalysis(
        schema_version=1,
        engine_version=ENGINE_VERSION,
        symbol=normalized_symbol,
        timeframe=timeframe,
        as_of_open_ms=window[-1].open_time_ms,
        as_of_close_ms=window[-1].close_time_ms,
        current_price=current,
        range_low=low,
        range_high=high,
        fibonacci_382=high - span * D("0.382"),
        fibonacci_500=midpoint,
        fibonacci_618=high - span * D("0.618"),
        trend_bps_per_bar=trend,
        momentum_20=momentum,
        volatility_20=volatility,
        primary_scenario=primary,
        bullish_weight=bullish,
        range_weight=ranging,
        bearish_weight=bearish,
        entry_condition=entry,
        invalidation_level=invalidation,
        target_level=target,
        shadow_action=action,
        probability_status="uncalibrated_scenario_weight",
    )


def realized_shadow_returns(
    *,
    action: str,
    entry_price: Decimal,
    exit_price: Decimal,
    round_trip_cost_pct: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return candidate, always-long baseline, and edge after costs."""
    try:
        entry = _finite(D(entry_price), "entry_price")
        exit_value = _finite(D(exit_price), "exit_price")
        cost = _finite(D(round_trip_cost_pct), "round_trip_cost_pct")
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("invalid exact return input") from exc
    if entry <= ZERO or exit_value <= ZERO or cost < ZERO or cost >= ONE:
        raise ValueError("invalid exact return boundary")
    baseline = exit_value / entry - ONE - cost
    candidate = baseline if action == "LONG" else ZERO if action == "CASH" else None
    if candidate is None:
        raise ValueError("unsupported SHADOW action")
    return candidate, baseline, candidate - baseline
