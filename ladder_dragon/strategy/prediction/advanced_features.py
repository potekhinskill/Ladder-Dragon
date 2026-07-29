# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: build chronological regime features unavailable in the base predictor.

"""Look-ahead-safe extended features for statistical regime research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import math
from typing import Mapping, Sequence

from ladder_dragon.strategy.prediction.models import PredictionBar


D = Decimal
ZERO = D("0")
ONE = D("1")


@dataclass(frozen=True)
class TimedMarketValue:
    timestamp_ms: int
    value: Decimal


@dataclass(frozen=True)
class ExtendedRegimeFeatures:
    snapshot_ts_ms: int
    realized_volatility_short: Decimal
    realized_volatility_long: Decimal
    volatility_ratio: Decimal
    vwap_deviation_pct: Decimal
    vwap_slope_pct: Decimal
    hour_sin: Decimal
    hour_cos: Decimal
    weekday_sin: Decimal
    weekday_cos: Decimal
    agg_trade_imbalance: Decimal
    agg_trade_available: bool
    funding_rate: Decimal | None
    funding_available: bool
    open_interest_change_pct: Decimal | None
    open_interest_available: bool

    def vector(self) -> tuple[Decimal, ...]:
        """Return a stable vector; missing external data is encoded separately."""
        return (
            self.realized_volatility_short,
            self.realized_volatility_long,
            self.volatility_ratio,
            self.vwap_deviation_pct,
            self.vwap_slope_pct,
            self.hour_sin,
            self.hour_cos,
            self.weekday_sin,
            self.weekday_cos,
            self.agg_trade_imbalance,
            self.funding_rate if self.funding_rate is not None else ZERO,
            ONE if self.funding_available else ZERO,
            (
                self.open_interest_change_pct
                if self.open_interest_change_pct is not None else ZERO
            ),
            ONE if self.open_interest_available else ZERO,
        )

    def as_json(self) -> dict[str, object]:
        return {
            key: format(value, "f") if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
        }


def _returns(bars: Sequence[PredictionBar]) -> list[Decimal]:
    return [
        current.close / previous.close - ONE
        for previous, current in zip(bars, bars[1:])
        if previous.close > 0
    ]


def _rms(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    variance = sum((value * value for value in values), ZERO) / D(str(len(values)))
    return D(str(math.sqrt(float(max(ZERO, variance)))))


def _vwap(bars: Sequence[PredictionBar]) -> Decimal:
    volume = sum((bar.volume for bar in bars), ZERO)
    if volume <= 0:
        return bars[-1].close
    return sum((bar.close * bar.volume for bar in bars), ZERO) / volume


def latest_known_value(
    values: Sequence[TimedMarketValue],
    *,
    as_of_ms: int,
    max_age_ms: int,
) -> Decimal | None:
    """Return only a value that existed by the feature cutoff."""
    eligible = [item for item in values if item.timestamp_ms <= as_of_ms]
    if not eligible:
        return None
    latest = max(eligible, key=lambda item: item.timestamp_ms)
    if as_of_ms - latest.timestamp_ms > max_age_ms:
        return None
    return latest.value if latest.value.is_finite() else None


def build_extended_features(
    bars: Sequence[PredictionBar],
    *,
    as_of_ms: int,
    agg_trade_imbalance: Decimal | None = None,
    funding: Sequence[TimedMarketValue] = (),
    open_interest: Sequence[TimedMarketValue] = (),
    short_window: int = 15,
    long_window: int = 60,
) -> ExtendedRegimeFeatures:
    """Build extended features exclusively from closed and timestamped inputs."""
    closed = sorted(
        (bar for bar in bars if bar.close_time_ms <= as_of_ms),
        key=lambda item: item.close_time_ms,
    )
    if len(closed) < long_window + 1:
        raise ValueError("insufficient closed bars for extended features")
    returns = _returns(closed)
    short_vol = _rms(returns[-short_window:])
    long_vol = _rms(returns[-long_window:])
    recent = closed[-20:]
    previous = closed[-40:-20]
    recent_vwap = _vwap(recent)
    previous_vwap = _vwap(previous)
    price = closed[-1].close
    timestamp_sec = as_of_ms // 1000
    day_seconds = timestamp_sec % 86_400
    weekday = (timestamp_sec // 86_400 + 3) % 7
    hour_angle = 2 * math.pi * day_seconds / 86_400
    weekday_angle = 2 * math.pi * weekday / 7
    funding_value = latest_known_value(
        funding,
        as_of_ms=as_of_ms,
        max_age_ms=9 * 60 * 60_000,
    )
    oi_now = latest_known_value(
        open_interest,
        as_of_ms=as_of_ms,
        max_age_ms=10 * 60_000,
    )
    prior_oi = latest_known_value(
        open_interest,
        as_of_ms=as_of_ms - 5 * 60_000,
        max_age_ms=10 * 60_000,
    )
    oi_change = (
        oi_now / prior_oi - ONE
        if oi_now is not None and prior_oi is not None and prior_oi > 0
        else None
    )
    flow = (
        max(-ONE, min(ONE, agg_trade_imbalance))
        if agg_trade_imbalance is not None and agg_trade_imbalance.is_finite()
        else ZERO
    )
    return ExtendedRegimeFeatures(
        snapshot_ts_ms=as_of_ms,
        realized_volatility_short=short_vol,
        realized_volatility_long=long_vol,
        volatility_ratio=short_vol / long_vol if long_vol > 0 else ONE,
        vwap_deviation_pct=price / recent_vwap - ONE if recent_vwap > 0 else ZERO,
        vwap_slope_pct=(
            recent_vwap / previous_vwap - ONE if previous_vwap > 0 else ZERO
        ),
        hour_sin=D(str(math.sin(hour_angle))),
        hour_cos=D(str(math.cos(hour_angle))),
        weekday_sin=D(str(math.sin(weekday_angle))),
        weekday_cos=D(str(math.cos(weekday_angle))),
        agg_trade_imbalance=flow,
        agg_trade_available=agg_trade_imbalance is not None,
        funding_rate=funding_value,
        funding_available=funding_value is not None,
        open_interest_change_pct=oi_change,
        open_interest_available=oi_change is not None,
    )


def ablation_vectors(
    features: ExtendedRegimeFeatures,
) -> Mapping[str, tuple[Decimal, ...]]:
    """Provide deterministic feature-family ablations for walk-forward reports."""
    full = features.vector()
    return {
        "full": full,
        "without_volatility": (ZERO, ZERO, ONE, *full[3:]),
        "without_vwap": (*full[:3], ZERO, ZERO, *full[5:]),
        "without_session": (*full[:5], ZERO, ONE, ZERO, ONE, *full[9:]),
        "without_microstructure": (*full[:9], ZERO, ZERO, ZERO, ZERO, ZERO),
    }
