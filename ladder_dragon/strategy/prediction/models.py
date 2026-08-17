# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define immutable prediction inputs, outputs and evaluation samples.

"""Prediction domain models."""

from dataclasses import dataclass
from decimal import Decimal
import json
from typing import Mapping


@dataclass(frozen=True)
class PredictionBar:
    open_time_ms: int
    close_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class PredictionFeatures:
    snapshot_ts_ms: int
    last_closed_bar_ts_ms: int
    price: Decimal
    ema_slope: Decimal
    ema_distance_pct: Decimal
    adx: Decimal
    plus_di: Decimal
    minus_di: Decimal
    atr_pct: Decimal
    atr_change_pct: Decimal
    vwap_deviation_pct: Decimal
    rsi: Decimal
    macd_histogram_pct: Decimal
    volume_ratio: Decimal
    orderbook_imbalance: Decimal
    orderbook_available: bool
    trade_flow_imbalance: Decimal
    trade_flow_available: bool
    spread_bps: Decimal
    depth_quote: Decimal
    acceleration: Decimal
    executor_panic_active: bool | None
    executor_panic_hits: int | None
    regime: str


@dataclass(frozen=True)
class TradePlan:
    entry_price: Decimal
    take_profit_price: Decimal
    stop_price: Decimal
    notional_quote: Decimal
    fee_pct: Decimal
    slippage_pct: Decimal
    entry_ttl_sec: int | None = None
    entry_enabled: bool = True

    def __post_init__(self) -> None:
        values = (
            self.entry_price,
            self.take_profit_price,
            self.stop_price,
            self.notional_quote,
            self.fee_pct,
            self.slippage_pct,
        )
        if any(not value.is_finite() for value in values):
            raise ValueError("trade plan values must be finite")
        if self.entry_price <= 0 or self.notional_quote <= 0:
            raise ValueError("entry price and notional must be positive")
        if not self.stop_price < self.entry_price < self.take_profit_price:
            raise ValueError("trade plan must satisfy stop < entry < take profit")
        if self.fee_pct < 0 or self.slippage_pct < 0:
            raise ValueError("execution costs must be non-negative")
        if self.entry_ttl_sec is not None and (
            isinstance(self.entry_ttl_sec, bool)
            or not isinstance(self.entry_ttl_sec, int)
            or self.entry_ttl_sec <= 0
        ):
            raise ValueError("entry TTL must be a positive integer")
        if not isinstance(self.entry_enabled, bool):
            raise ValueError("entry_enabled must be boolean")


@dataclass(frozen=True)
class HorizonPrediction:
    horizon_min: int
    probability_buy_fill: Decimal
    probability_tp_before_stop: Decimal
    expected_net_pnl_quote: Decimal
    expected_mae_pct: Decimal
    expected_time_to_fill_sec: Decimal
    samples: int
    available: bool


@dataclass(frozen=True)
class PredictionOutcome:
    horizon_min: int
    buy_filled: bool
    tp_before_stop: bool | None
    net_pnl_quote: Decimal
    mae_pct: Decimal
    time_to_fill_sec: int | None
    exit_reason: str
    resolved_at_ms: int


@dataclass(frozen=True)
class ResolvedSample:
    snapshot_ts_ms: int
    regime: str
    horizon_min: int
    outcome: PredictionOutcome
    baseline_net_pnl_quote: Decimal
    decision_metadata: Mapping[str, object] | None = None


def decision_metadata(raw: str) -> Mapping[str, object] | None:
    """Return structured decision metadata, or none for historical text records."""
    if not raw.startswith("{"):
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
