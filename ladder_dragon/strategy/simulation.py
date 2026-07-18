# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: implement the simulation component of the strategy layer.
"""Deterministic, Decimal-based execution simulator for strategy tests."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence
import random
import os
from pathlib import Path


D = Decimal


@dataclass(frozen=True)
class Candle:
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = D("0")
    bid: Decimal = D("0")
    ask: Decimal = D("0")


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
    min_net_edge_pct: Decimal = D("0.001")
    max_holding_bars: int = 0
    latency_bars: int = 1
    queue_ahead_ratio: Decimal = D("0")
    participation_rate: Decimal = D("1")
    market_impact_bps: Decimal = D("0")
    cancel_after_bars: int = 0


@dataclass
class SimulationResult:
    final_equity: Decimal
    realized_pnl: Decimal
    fees: Decimal
    trades: int
    buy_hold_equity: Decimal


class Inventory:
    """Портфель симулятора с агрегированной стоимостью и FIFO-партиями."""
    def __init__(self) -> None:
        self.qty = D("0")
        self.avg_cost = D("0")
        self.realized = D("0")
        self.fees = D("0")
        self.lots: list[dict[str, Decimal | int]] = []

    def buy(self, price: Decimal, qty: Decimal, fee: Decimal, *, opened_index: int = 0) -> None:
        new_qty = self.qty + qty
        self.avg_cost = ((self.avg_cost * self.qty) + (price * qty) + fee) / new_qty
        self.qty = new_qty
        self.fees += fee
        self.lots.append({"qty": qty, "price": price, "opened_index": opened_index})

    def sell(self, price: Decimal, qty: Decimal, fee: Decimal) -> None:
        if qty > self.qty:
            raise ValueError("cannot sell more than simulated inventory")
        remaining = qty
        fifo_cost = D("0")
        # FIFO is required for correct time-stop behavior and reproducible PnL.
        while remaining > 0 and self.lots:
            lot = self.lots[0]
            used = min(remaining, D(str(lot["qty"])))
            fifo_cost += (price - D(str(lot["price"]))) * used
            lot["qty"] = D(str(lot["qty"])) - used
            remaining -= used
            if D(str(lot["qty"])) <= D("1e-18"):
                self.lots.pop(0)
        self.realized += fifo_cost - fee
        self.qty -= qty
        self.fees += fee
        if self.qty == 0:
            self.avg_cost = D("0")

    def oldest_age(self, current_index: int) -> int:
        if not self.lots:
            return 0
        return max(0, current_index - int(self.lots[0]["opened_index"]))


def simulate_grid(candles: Sequence[Candle], config: SimulationConfig, *, market_events: Sequence[object] | None = None) -> SimulationResult:
    """Запустить backtest на OHLC или на записанном order-book feed.

    При наличии событий стакана они становятся источником bid/ask/volume для
    каждой свечи; остальная стратегия и accounting остаются общими.
    """
    if market_events is not None:
        # The order book enriches candles without changing the strategy, so
        # OHLC and order-book results remain comparable on the same code.
        by_ts = {int(getattr(event, "ts_ms", -1)): event for event in market_events}
        enriched = []
        for candle in candles:
            event = by_ts.get(int(candle.ts)) or by_ts.get(int(candle.ts) * 1000)
            if event is None:
                enriched.append(candle)
                continue
            bids = getattr(event, "bids", ())
            asks = getattr(event, "asks", ())
            bid = bids[0].price if bids else candle.bid
            ask = asks[0].price if asks else candle.ask
            volume = sum((level.quantity for level in (*bids, *asks)), D("0"))
            enriched.append(Candle(candle.ts, candle.open, candle.high, candle.low,
                                   candle.close, volume=volume, bid=bid, ask=ask))
        candles = enriched
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
    if config.min_net_edge_pct < 0 or config.max_holding_bars < 0:
        raise ValueError("min_net_edge_pct and max_holding_bars must be non-negative")
    if not D("0") <= config.queue_ahead_ratio < D("1") or not D("0") < config.participation_rate <= D("1"):
        raise ValueError("queue_ahead_ratio must be in [0,1), participation_rate in (0,1]")
    round_trip_cost = D("2") * (
        config.fee_pct + config.slippage_pct + config.spread_pct / D("2")
    )
    if config.take_profit_pct - round_trip_cost < config.min_net_edge_pct:
        raise ValueError("take-profit does not clear the configured minimum net edge")

    cash = config.initial_cash
    inventory = Inventory()
    trades = 0
    pending_buy: tuple[int, Decimal, Decimal] | None = None
    # (eligible bar, take-profit, stop-loss; stop=0 means disabled)
    pending_sell: tuple[int, Decimal, Decimal] | None = None
    position_open_index: int | None = None

    for index, candle in enumerate(candles):
        # BUY executes only after latency and when the limit price is touched.
        if pending_buy and index >= pending_buy[0] and candle.low <= pending_buy[1] and cash >= config.order_notional:
            # BUY pays half-spread plus adverse slippage. A touched limit is
            # not considered filled if that adverse execution is outside the
            # candle range; this avoids impossible OHLC fills.
            book_ask = candle.ask if candle.ask > 0 else pending_buy[1]
            execution = book_ask * (D("1") + config.slippage_pct + config.spread_pct / D("2"))
            execution *= D("1") + config.market_impact_bps / D("100000")
            if execution > candle.high:
                continue
            available_ratio = config.partial_fill_ratio
            if candle.volume > 0:
                # Candle volume and queue-ahead replace an artificial full fill;
                # participation limits liquidity available to the order.
                available_ratio = min(available_ratio, max(D("0"), D("1") - config.queue_ahead_ratio) * config.participation_rate)
            qty = min(
                pending_buy[2],
                config.order_notional / execution,
            ) * available_ratio
            fee = execution * qty * config.fee_pct
            if cash >= execution * qty + fee:
                cash -= execution * qty + fee
                inventory.buy(execution, qty, fee, opened_index=index)
                trades += 1
                position_open_index = position_open_index or index
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

        forced_exit = (
            position_open_index is not None
            and config.max_holding_bars > 0
            and inventory.oldest_age(index) >= config.max_holding_bars
            and inventory.qty > 0
        )
        if forced_exit:
            execution = candle.close * (
                D("1") - config.slippage_pct - config.spread_pct / D("2")
            )
            if execution >= candle.low:
                qty = inventory.qty
                fee = execution * qty * config.fee_pct
                inventory.sell(execution, qty, fee)
                cash += execution * qty - fee
                trades += 1
                pending_sell = None
                position_open_index = None

        # When both OCO legs trigger in one OHLC candle, stop wins conservatively.
        if pending_sell and not forced_exit and index >= pending_sell[0] and inventory.qty > 0:
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
                execution *= D("1") - config.market_impact_bps / D("100000")
                if execution >= candle.low:
                    sell_ratio = config.partial_fill_ratio
                    if candle.volume > 0:
                        sell_ratio = min(sell_ratio, config.participation_rate)
                    qty = inventory.qty * sell_ratio
                    fee = execution * qty * config.fee_pct
                    inventory.sell(execution, qty, fee)
                    cash += execution * qty - fee
                    trades += 1
                    if inventory.qty <= D("1e-18"):
                        pending_sell = None
                        position_open_index = None

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


def walk_forward(
    candles: Sequence[Candle], configs: Iterable[SimulationConfig], folds: int = 3,
    *, purge_bars: int = 1, embargo_bars: int = 1,
) -> list[dict]:
    if folds < 2 or len(candles) < folds * 3:
        raise ValueError("insufficient data for walk-forward folds")
    configs = list(configs)
    if not configs:
        raise ValueError("at least one configuration is required")
    if purge_bars < 0 or embargo_bars < 0:
        raise ValueError("purge_bars and embargo_bars must be non-negative")
    size = len(candles) // folds
    results: list[dict] = []
    for fold in range(1, folds):
        boundary = fold * size
        train_end = max(1, boundary - purge_bars)
        test_start = min(len(candles), boundary + embargo_bars)
        train = candles[:train_end]
        test = candles[test_start: (fold + 1) * size]
        if not train or not test:
            continue
        best = max(configs, key=lambda cfg: simulate_grid(train, cfg).final_equity)
        score = simulate_grid(test, best)
        results.append({"fold": fold, "config": best, "result": score,
                        "purge_bars": purge_bars, "embargo_bars": embargo_bars})
    return results


def bootstrap_confidence_interval(values: Sequence[Decimal], *, confidence: float = 0.95,
                                  iterations: int = 1000, seed: int = 7) -> tuple[Decimal, Decimal]:
    """Воспроизводимый bootstrap CI для fold returns/PnL."""
    if not values or not 0 < confidence < 1 or iterations <= 0:
        raise ValueError("values, confidence and iterations are invalid")
    rng = random.Random(seed)
    samples = []
    for _ in range(iterations):
        draw = [values[rng.randrange(len(values))] for _ in values]
        samples.append(sum(draw, D("0")) / D(str(len(draw))))
    samples.sort()
    alpha = (1.0 - confidence) / 2.0
    return samples[int(alpha * (len(samples) - 1))], samples[int((1.0 - alpha) * (len(samples) - 1))]


def cost_robustness(candles: Sequence[Candle], config: SimulationConfig,
                    *, slippage_multipliers: Sequence[Decimal] = (D("0.5"), D("1"), D("2"))) -> dict[Decimal, SimulationResult]:
    """Проверить, что результат не зависит от одной идеальной оценки slippage."""
    result = {}
    for multiplier in slippage_multipliers:
        result[multiplier] = simulate_grid(candles, SimulationConfig(**{
            **config.__dict__, "slippage_pct": config.slippage_pct * multiplier,
        }))
    return result


def production_walk_forward(candles: Sequence[Candle], configs: Iterable[SimulationConfig],
                            *, folds: int = 3, purge_bars: int = 2,
                            embargo_bars: int = 2, inner_folds: int = 2,
                            confidence: float = 0.95) -> dict:
    """Nested walk-forward отчёт с cost robustness и CI.

    Inner folds выбирают параметры только внутри train; outer test никогда не
    участвует в selection. Конфигурация помечается degraded, если медианный
    результат не превосходит ноль или CI пересекает отрицательную область.
    """
    # Select all parameters on train; use the outer test exactly once.
    configs = list(configs)
    if len(configs) < 2:
        raise ValueError("nested walk-forward requires at least two configs")
    outer = []
    size = len(candles) // folds
    for fold in range(1, folds):
        boundary = fold * size
        train_end = max(1, boundary - purge_bars)
        test_start = min(len(candles), boundary + embargo_bars)
        train, test = candles[:train_end], candles[test_start:(fold + 1) * size]
        if not train or not test:
            continue
        # Inner folds select a configuration only within train.
        inner_size = max(1, len(train) // max(2, inner_folds + 1))
        scores = []
        for cfg in configs:
            inner_scores = []
            for inner in range(1, max(2, inner_folds + 1)):
                end = min(len(train), inner * inner_size)
                if end <= 1:
                    continue
                inner_scores.append(simulate_grid(train[:end], cfg).final_equity)
            scores.append((sum(inner_scores, D("0")) / max(1, len(inner_scores)), cfg))
        best = max(scores, key=lambda item: item[0])[1]
        outer.append({"fold": fold, "config": best, "result": simulate_grid(test, best),
                      "purge_bars": purge_bars, "embargo_bars": embargo_bars})
    returns = [item["result"].final_equity - item["result"].buy_hold_equity for item in outer]
    ci = bootstrap_confidence_interval(returns, confidence=confidence) if returns else (D("0"), D("0"))
    # Bonferroni-style conservative threshold for multiple configurations.
    adjusted_alpha = (D("1") - D(str(confidence))) / max(1, len(configs))
    report = {
        "folds": outer,
        "excess_returns": returns,
        "confidence_interval": ci,
        "adjusted_alpha": adjusted_alpha,
        "degraded": not returns or ci[1] <= 0,
        "cost_robustness": [cost_robustness(candles, item["config"]) for item in outer],
        "inner_folds": inner_folds,
    }
    # CI or deployment can consume this fail-closed marker: degraded parameters
    # must never enter LIVE configuration automatically.
    lock_path = os.getenv("BOT_PARAM_LOCK_FILE", "")
    if report["degraded"] and lock_path:
        Path(lock_path).write_text("degraded\n", encoding="utf-8")
    return report


def multi_period_walk_forward(periods: Sequence[Sequence[Candle]], configs: Iterable[SimulationConfig], **kwargs) -> dict:
    """Прогнать walk-forward на независимых исторических периодах/режимах."""
    reports = [production_walk_forward(period, configs, **kwargs) for period in periods if period]
    degraded = any(report["degraded"] for report in reports) or not reports
    return {"periods": reports, "degraded": degraded,
            "excess_returns": [value for report in reports for value in report["excess_returns"]]}


def holm_bonferroni(p_values: Sequence[float], alpha: float = 0.05) -> list[bool]:
    """Holm multiple-testing correction: отклонить ложные улучшения параметров."""
    indexed = sorted(enumerate(float(value) for value in p_values), key=lambda item: item[1])
    accepted = [False] * len(indexed)
    for rank, (index, value) in enumerate(indexed):
        if value <= alpha / max(1, len(indexed) - rank):
            accepted[index] = True
        else:
            break
    return accepted


def approve_production_report(report: dict, *, min_folds: int = 3,
                              min_lower_ci: Decimal = D("0")) -> dict:
    """Fail-closed approval: degraded/неустойчивые параметры запрещаются."""
    returns = report.get("excess_returns", [])
    ci = report.get("confidence_interval", (D("0"), D("0")))
    approved = bool(returns) and len(returns) >= min_folds and not report.get("degraded", True) and ci[0] >= min_lower_ci
    return {"approved": approved, "reason": "approved" if approved else "walk-forward stability gate failed",
            "folds": len(returns), "confidence_interval": ci}


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
