"""Deterministic, Decimal-based execution simulator for strategy tests."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence


D = Decimal


@dataclass(frozen=True)
class Candle:
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class SimulationConfig:
    initial_cash: Decimal = D("1000")
    order_notional: Decimal = D("50")
    buy_offset_pct: Decimal = D("0.01")
    take_profit_pct: Decimal = D("0.01")
    fee_pct: Decimal = D("0.00075")
    slippage_pct: Decimal = D("0.0005")
    spread_pct: Decimal = D("0.0002")
    latency_bars: int = 1


@dataclass
class SimulationResult:
    final_equity: Decimal
    realized_pnl: Decimal
    fees: Decimal
    trades: int
    buy_hold_equity: Decimal


class Inventory:
    def __init__(self) -> None:
        self.qty = D("0")
        self.avg_cost = D("0")
        self.realized = D("0")
        self.fees = D("0")

    def buy(self, price: Decimal, qty: Decimal, fee: Decimal) -> None:
        new_qty = self.qty + qty
        self.avg_cost = ((self.avg_cost * self.qty) + (price * qty) + fee) / new_qty
        self.qty = new_qty
        self.fees += fee

    def sell(self, price: Decimal, qty: Decimal, fee: Decimal) -> None:
        if qty > self.qty:
            raise ValueError("cannot sell more than simulated inventory")
        self.realized += (price - self.avg_cost) * qty - fee
        self.qty -= qty
        self.fees += fee
        if self.qty == 0:
            self.avg_cost = D("0")


def simulate_grid(candles: Sequence[Candle], config: SimulationConfig) -> SimulationResult:
    if len(candles) < config.latency_bars + 2:
        raise ValueError("not enough candles for configured latency")
    if config.initial_cash <= 0 or config.order_notional <= 0:
        raise ValueError("cash and order notional must be positive")
    if config.latency_bars < 1:
        raise ValueError("latency_bars must be at least 1 to avoid same-candle lookahead")
    if config.fee_pct < 0 or config.slippage_pct < 0 or config.spread_pct < 0:
        raise ValueError("fees, slippage and spread must be non-negative")

    cash = config.initial_cash
    inventory = Inventory()
    trades = 0
    pending_buy: tuple[int, Decimal] | None = None
    pending_sell: tuple[int, Decimal] | None = None

    for index, candle in enumerate(candles):
        if pending_buy and index >= pending_buy[0] and candle.low <= pending_buy[1] and cash >= config.order_notional:
            # BUY pays half-spread plus adverse slippage. A touched limit is
            # not considered filled if that adverse execution is outside the
            # candle range; this avoids impossible OHLC fills.
            execution = pending_buy[1] * (
                D("1") + config.slippage_pct + config.spread_pct / D("2")
            )
            if execution > candle.high:
                continue
            qty = config.order_notional / execution
            fee = execution * qty * config.fee_pct
            if cash >= execution * qty + fee:
                cash -= execution * qty + fee
                inventory.buy(execution, qty, fee)
                trades += 1
                target = execution * (D("1") + config.take_profit_pct)
                pending_sell = (index + config.latency_bars, target)
            pending_buy = None

        if pending_sell and index >= pending_sell[0] and candle.high >= pending_sell[1] and inventory.qty > 0:
            execution = pending_sell[1] * (
                D("1") - config.slippage_pct - config.spread_pct / D("2")
            )
            if execution < candle.low:
                continue
            qty = inventory.qty
            fee = execution * qty * config.fee_pct
            inventory.sell(execution, qty, fee)
            cash += execution * qty - fee
            trades += 1
            pending_sell = None

        if pending_buy is None and inventory.qty == 0:
            pending_buy = (
                index + config.latency_bars,
                candle.close * (D("1") - config.buy_offset_pct),
            )

    final_equity = cash + inventory.qty * candles[-1].close
    initial_qty = config.initial_cash / candles[0].close
    buy_hold = initial_qty * candles[-1].close
    return SimulationResult(final_equity, inventory.realized, inventory.fees, trades, buy_hold)


def walk_forward(candles: Sequence[Candle], configs: Iterable[SimulationConfig], folds: int = 3) -> list[dict]:
    if folds < 2 or len(candles) < folds * 3:
        raise ValueError("insufficient data for walk-forward folds")
    configs = list(configs)
    if not configs:
        raise ValueError("at least one configuration is required")
    size = len(candles) // folds
    results: list[dict] = []
    for fold in range(1, folds):
        train = candles[: fold * size]
        test = candles[fold * size: (fold + 1) * size]
        best = max(configs, key=lambda cfg: simulate_grid(train, cfg).final_equity)
        score = simulate_grid(test, best)
        results.append({"fold": fold, "config": best, "result": score})
    return results
