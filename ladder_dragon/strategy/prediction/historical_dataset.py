# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: create chronological prediction samples from verified closed bars.

"""Historical, multi-symbol datasets with explicit look-ahead boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from ladder_dragon.strategy.prediction.advanced_features import (
    ExtendedRegimeFeatures,
    TimedMarketValue,
    build_extended_features,
)
from ladder_dragon.strategy.prediction.models import PredictionBar


D = Decimal
ONE = D("1")


@dataclass(frozen=True)
class HistoricalRegimeSample:
    symbol: str
    snapshot_ts_ms: int
    label_ts_ms: int
    horizon_min: int
    features: ExtendedRegimeFeatures
    realized_return: Decimal
    label: str


@dataclass(frozen=True)
class SymbolAuxiliaryHistory:
    """Timestamped public values captured with the historical market archive."""

    agg_trade_imbalance_by_close_ms: Mapping[int, Decimal]
    funding: Sequence[TimedMarketValue] = ()
    open_interest: Sequence[TimedMarketValue] = ()


def _label(value: Decimal, threshold: Decimal) -> str:
    if value > threshold:
        return "UP"
    if value < -threshold:
        return "DOWN"
    return "FLAT"


def build_historical_samples(
    symbol_bars: Mapping[str, Sequence[PredictionBar]],
    *,
    auxiliary: Mapping[str, SymbolAuxiliaryHistory] | None = None,
    horizons_min: Sequence[int] = (1, 5, 15),
    flat_threshold: Decimal = D("0.001"),
) -> list[HistoricalRegimeSample]:
    """Generate samples whose features end strictly before their labels."""
    if flat_threshold < 0:
        raise ValueError("flat_threshold must be non-negative")
    samples: list[HistoricalRegimeSample] = []
    for raw_symbol, raw_bars in sorted(symbol_bars.items()):
        symbol = raw_symbol.upper()
        if not symbol or not symbol.isalnum():
            raise ValueError("symbol must be alphanumeric")
        bars = sorted(raw_bars, key=lambda item: item.close_time_ms)
        if any(
            current.open_time_ms - previous.open_time_ms != 60_000
            or current.close_time_ms - current.open_time_ms != 59_999
            for previous, current in zip(bars, bars[1:])
        ):
            raise ValueError(
                f"{symbol} historical bars must be contiguous closed minutes"
            )
        extra = (auxiliary or {}).get(symbol)
        for index in range(61, len(bars)):
            snapshot = bars[index - 1]
            features = build_extended_features(
                bars[:index],
                as_of_ms=snapshot.close_time_ms,
                agg_trade_imbalance=(
                    extra.agg_trade_imbalance_by_close_ms.get(snapshot.close_time_ms)
                    if extra is not None else None
                ),
                funding=extra.funding if extra is not None else (),
                open_interest=extra.open_interest if extra is not None else (),
            )
            for horizon in horizons_min:
                target_index = index - 1 + int(horizon)
                if horizon <= 0 or target_index >= len(bars):
                    continue
                target = bars[target_index]
                if target.close_time_ms <= snapshot.close_time_ms:
                    raise ValueError("historical label is not after its snapshot")
                realized = target.close / snapshot.close - ONE
                samples.append(HistoricalRegimeSample(
                    symbol=symbol,
                    snapshot_ts_ms=snapshot.close_time_ms,
                    label_ts_ms=target.close_time_ms,
                    horizon_min=int(horizon),
                    features=features,
                    realized_return=realized,
                    label=_label(realized, flat_threshold),
                ))
    return samples


def expanding_walk_forward_splits(
    samples: Sequence[HistoricalRegimeSample],
    *,
    min_train_samples: int,
) -> list[tuple[tuple[HistoricalRegimeSample, ...], HistoricalRegimeSample]]:
    """Return only splits where every training label predates the test snapshot."""
    ordered = sorted(samples, key=lambda item: (item.snapshot_ts_ms, item.symbol))
    output = []
    for test in ordered:
        train = tuple(
            row for row in ordered
            if row.label_ts_ms < test.snapshot_ts_ms
        )
        if len(train) >= min_train_samples:
            output.append((train, test))
    return output
