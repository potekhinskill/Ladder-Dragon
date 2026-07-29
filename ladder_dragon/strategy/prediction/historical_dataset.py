# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: create chronological prediction samples from verified closed bars.

"""Historical, multi-symbol datasets with explicit look-ahead boundaries."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence, overload

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


@dataclass(frozen=True)
class WalkForwardTrainingPrefix(Sequence[HistoricalRegimeSample]):
    """Read-only prefix view that does not copy an expanding training set."""

    _rows: tuple[HistoricalRegimeSample, ...]
    _stop: int

    def __len__(self) -> int:
        return self._stop

    @overload
    def __getitem__(self, index: int) -> HistoricalRegimeSample:
        ...

    @overload
    def __getitem__(self, index: slice) -> tuple[HistoricalRegimeSample, ...]:
        ...

    def __getitem__(
        self,
        index: int | slice,
    ) -> HistoricalRegimeSample | tuple[HistoricalRegimeSample, ...]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self._stop)
            return self._rows[start:stop:step]
        normalized = index + self._stop if index < 0 else index
        if normalized < 0 or normalized >= self._stop:
            raise IndexError(index)
        return self._rows[normalized]


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
) -> Iterator[
    tuple[WalkForwardTrainingPrefix, HistoricalRegimeSample]
]:
    """Yield purged splits in O(n log n) without copying growing prefixes."""
    if min_train_samples < 0:
        raise ValueError("min_train_samples must be non-negative")
    tests = sorted(
        samples,
        key=lambda item: (item.snapshot_ts_ms, item.symbol, item.horizon_min),
    )
    training_rows = tuple(sorted(
        samples,
        key=lambda item: (
            item.label_ts_ms,
            item.snapshot_ts_ms,
            item.symbol,
            item.horizon_min,
        ),
    ))
    label_timestamps = tuple(row.label_ts_ms for row in training_rows)
    for test in tests:
        stop = bisect_left(label_timestamps, test.snapshot_ts_ms)
        if stop >= min_train_samples:
            yield WalkForwardTrainingPrefix(training_rows, stop), test
