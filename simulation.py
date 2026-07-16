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
    partial_fill_ratio: Decimal = D("1")
    stop_loss_pct: Decimal = D("0")
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
    if not D("0") < config.partial_fill_ratio <= D("1"):
        raise ValueError("partial_fill_ratio must be in (0, 1]")
    if config.stop_loss_pct < 0 or config.stop_loss_pct >= D("1"):
        raise ValueError("stop_loss_pct must be in [0, 1)")

    cash = config.initial_cash
    inventory = Inventory()
    trades = 0
    pending_buy: tuple[int, Decimal, Decimal] | None = None
    # (eligible bar, take-profit, stop-loss; stop=0 means disabled)
    pending_sell: tuple[int, Decimal, Decimal] | None = None

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
            qty = min(
                pending_buy[2],
                config.order_notional / execution,
            ) * config.partial_fill_ratio
            fee = execution * qty * config.fee_pct
            if cash >= execution * qty + fee:
                cash -= execution * qty + fee
                inventory.buy(execution, qty, fee)
                trades += 1
                target = execution * (D("1") + config.take_profit_pct)
                stop = (
                    execution * (D("1") - config.stop_loss_pct)
                    if config.stop_loss_pct > 0 else D("0")
                )
                pending_sell = (index + config.latency_bars, target, stop)
                remaining = pending_buy[2] - qty
                pending_buy = (
                    (pending_buy[0], pending_buy[1], remaining)
                    if remaining > D("1e-18") else None
                )

        if pending_sell and index >= pending_sell[0] and inventory.qty > 0:
            take_profit, stop_loss = pending_sell[1], pending_sell[2]
            stop_hit = stop_loss > 0 and candle.low <= stop_loss
            target_hit = candle.high >= take_profit
            # If both OCO legs are touched in one OHLC bar, assume the stop
            # fired first. Without tick data this is the conservative choice.
            if not stop_hit and not target_hit:
                pass
            else:
                trigger = stop_loss if stop_hit else take_profit
                execution = trigger * (
                    D("1") - config.slippage_pct - config.spread_pct / D("2")
                )
                if execution >= candle.low:
                    qty = inventory.qty * config.partial_fill_ratio
                    fee = execution * qty * config.fee_pct
                    inventory.sell(execution, qty, fee)
                    cash += execution * qty - fee
                    trades += 1
                    if inventory.qty <= D("1e-18"):
                        pending_sell = None

        if pending_buy is None and inventory.qty == 0:
            pending_buy = (
                index + config.latency_bars,
                candle.close * (D("1") - config.buy_offset_pct),
                config.order_notional / max(
                    D("1e-18"), candle.close * (D("1") - config.buy_offset_pct)
                ),
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


def stress_grid(
    candles: Sequence[Candle],
    config: SimulationConfig,
    shocks: Iterable[Decimal] = (D("-0.30"), D("-0.20"), D("-0.10"), D("0")),
) -> dict[Decimal, SimulationResult]:
    """Replay the same path after simultaneous price shocks.

    This is a coarse portfolio stress test, not a replacement for tick-level
    replay: it makes the downside scenarios explicit and reproducible.
    """
    result: dict[Decimal, SimulationResult] = {}
    for shock in shocks:
        factor = D("1") + D(str(shock))
        if factor <= 0:
            raise ValueError("stress shock must leave positive prices")
        shifted = [
            Candle(
                candle.ts,
                candle.open * factor,
                candle.high * factor,
                candle.low * factor,
                candle.close * factor,
            )
            for candle in candles
        ]
        result[D(str(shock))] = simulate_grid(shifted, config)
    return result
