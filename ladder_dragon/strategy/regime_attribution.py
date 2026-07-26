# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: attribute exact FIFO results and comparable benchmarks by regime.
"""Exact realized-PnL attribution using only past regime snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from ladder_dragon.execution.trade_accounting import TradeExecution


ZERO = Decimal("0")
REPORT_REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN", "PANIC")


@dataclass(frozen=True)
class RegimeSnapshot:
    symbol: str
    timestamp_ms: int
    regime: str
    price: Decimal


@dataclass(frozen=True)
class TimedExecution:
    timestamp_ms: int
    trade: TradeExecution


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    strategy_net_pnl: Decimal
    buy_hold_net_pnl: Decimal
    usdt_pnl: Decimal
    realized_drawdown: Decimal
    samples: int
    fill_rate: Decimal | None
    candidate_samples: int


def _latest_snapshot(
    snapshots: Sequence[RegimeSnapshot],
    *,
    symbol: str,
    timestamp_ms: int,
    max_age_ms: int,
) -> RegimeSnapshot:
    eligible = [
        item
        for item in snapshots
        if item.symbol == symbol and item.timestamp_ms <= timestamp_ms
    ]
    if not eligible:
        raise ValueError(f"missing past regime snapshot for {symbol}")
    latest = max(eligible, key=lambda item: item.timestamp_ms)
    if timestamp_ms - latest.timestamp_ms > max_age_ms:
        raise ValueError(f"stale regime snapshot for {symbol}")
    if latest.regime not in REPORT_REGIMES or latest.price <= ZERO:
        raise ValueError(f"invalid regime snapshot for {symbol}")
    return latest


def attribute_fifo_by_regime(
    executions: Sequence[TimedExecution],
    snapshots: Sequence[RegimeSnapshot],
    *,
    window_start_ms: int,
    window_end_ms: int,
    end_prices: Mapping[str, Decimal],
    benchmark_exit_fee_pct: Decimal,
    max_snapshot_age_ms: int = 15 * 60_000,
    fill_observations: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[RegimeResult, ...]:
    """Compare realized strategy PnL with holding each consumed FIFO lot.

    The USDT benchmark is exactly zero for the same committed capital. The
    buy-and-hold benchmark values each consumed lot at the report-end price,
    deducting the same recorded BUY cost and one explicit hypothetical exit
    fee. Missing historical regimes or prices block the report.
    """
    if (
        window_start_ms < 0
        or window_end_ms <= window_start_ms
        or benchmark_exit_fee_pct < ZERO
        or max_snapshot_age_ms <= 0
    ):
        raise ValueError("regime attribution bounds are invalid")
    lots: dict[str, list[list[object]]] = {}
    pnl = {regime: ZERO for regime in REPORT_REGIMES}
    hold = {regime: ZERO for regime in REPORT_REGIMES}
    samples = {regime: 0 for regime in REPORT_REGIMES}
    curves = {regime: [ZERO] for regime in REPORT_REGIMES}

    for timed in sorted(executions, key=lambda item: item.timestamp_ms):
        if timed.timestamp_ms >= window_end_ms:
            continue
        trade = timed.trade
        symbol_lots = lots.setdefault(trade.symbol, [])
        if trade.side == "BUY":
            snapshot = _latest_snapshot(
                snapshots,
                symbol=trade.symbol,
                timestamp_ms=timed.timestamp_ms,
                max_age_ms=max_snapshot_age_ms,
            )
            symbol_lots.append([
                trade.net_qty,
                trade.buy_cost_quote(),
                snapshot.regime,
            ])
            continue
        remaining = trade.net_qty
        proceeds = trade.sell_proceeds_quote()
        while remaining > ZERO and symbol_lots:
            lot_qty = Decimal(symbol_lots[0][0])
            lot_cost = Decimal(symbol_lots[0][1])
            regime = str(symbol_lots[0][2])
            take = min(remaining, lot_qty)
            cost_take = lot_cost * take / lot_qty
            proceeds_take = proceeds * take / trade.net_qty
            if window_start_ms <= timed.timestamp_ms < window_end_ms:
                end_price = end_prices.get(trade.symbol)
                if end_price is None or end_price <= ZERO:
                    raise ValueError(
                        f"missing report-end price for {trade.symbol}"
                    )
                strategy_value = proceeds_take - cost_take
                hold_value = (
                    end_price
                    * take
                    * (Decimal("1") - benchmark_exit_fee_pct)
                    - cost_take
                )
                pnl[regime] += strategy_value
                hold[regime] += hold_value
                samples[regime] += 1
                curves[regime].append(curves[regime][-1] + strategy_value)
            remaining -= take
            lot_qty -= take
            lot_cost -= cost_take
            if lot_qty <= ZERO:
                symbol_lots.pop(0)
            else:
                symbol_lots[0] = [lot_qty, lot_cost, regime]
        if remaining > ZERO:
            raise ValueError(
                f"incomplete FIFO history for {trade.symbol}"
            )

    results = []
    observed_fills = fill_observations or {}
    for regime in REPORT_REGIMES:
        peak = curves[regime][0]
        drawdown = ZERO
        for value in curves[regime]:
            peak = max(peak, value)
            drawdown = max(drawdown, peak - value)
        filled, candidates = observed_fills.get(regime, (0, 0))
        if filled < 0 or candidates < 0 or filled > candidates:
            raise ValueError("fill observations are invalid")
        results.append(RegimeResult(
            regime=regime,
            strategy_net_pnl=pnl[regime],
            buy_hold_net_pnl=hold[regime],
            usdt_pnl=ZERO,
            realized_drawdown=drawdown,
            samples=samples[regime],
            fill_rate=(
                Decimal(filled) / Decimal(candidates)
                if candidates
                else None
            ),
            candidate_samples=candidates,
        ))
    return tuple(results)
