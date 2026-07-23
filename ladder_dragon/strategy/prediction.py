# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: build look-ahead-safe technical predictions and SHADOW outcomes.
"""Chronological technical prediction and counterfactual SHADOW accounting.

The module has no exchange or order capability.  Runtime callers provide closed
bars and sanitized L2 aggregates; every decision is immutable and outcomes are
eligible only after their horizon has elapsed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import time
from typing import Iterable, Mapping, Sequence


D = Decimal
ZERO = D("0")
ONE = D("1")
HORIZONS_MIN = (1, 5, 15)
PREDICTION_SCHEMA_VERSION = 1


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _ema(values: Sequence[Decimal], length: int) -> list[Decimal]:
    if not values:
        return []
    alpha = D("2") / D(str(max(1, length) + 1))
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (ONE - alpha) * output[-1])
    return output


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


def parse_closed_klines(
    klines: Sequence[Sequence[object]],
    *,
    as_of_ms: int,
) -> list[PredictionBar]:
    """Parse only bars that were fully closed at the decision timestamp."""
    bars: list[PredictionBar] = []
    for row in klines:
        if len(row) < 7:
            continue
        try:
            open_time = int(row[0])
            close_time = int(row[6])
            bar = PredictionBar(
                open_time_ms=open_time,
                close_time_ms=close_time,
                open=_decimal(row[1], field="open"),
                high=_decimal(row[2], field="high"),
                low=_decimal(row[3], field="low"),
                close=_decimal(row[4], field="close"),
                volume=_decimal(row[5], field="volume"),
            )
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            close_time <= as_of_ms
            and bar.low > 0
            and bar.low <= bar.high
            and bar.volume >= 0
        ):
            bars.append(bar)
    bars.sort(key=lambda item: item.open_time_ms)
    return bars


def _directional_indicators(
    bars: Sequence[PredictionBar], length: int = 14
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    true_ranges: list[Decimal] = []
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    for previous, current in zip(bars, bars[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
        upward = current.high - previous.high
        downward = previous.low - current.low
        plus_dm.append(upward if upward > downward and upward > 0 else ZERO)
        minus_dm.append(downward if downward > upward and downward > 0 else ZERO)
    if len(true_ranges) < length * 2:
        raise ValueError("at least 29 closed bars are required")
    recent_tr = sum(true_ranges[-length:], ZERO) / D(str(length))
    previous_tr = sum(true_ranges[-2 * length:-length], ZERO) / D(str(length))
    plus = sum(plus_dm[-length:], ZERO) / D(str(length))
    minus = sum(minus_dm[-length:], ZERO) / D(str(length))
    plus_di = D("100") * plus / recent_tr if recent_tr > 0 else ZERO
    minus_di = D("100") * minus / recent_tr if recent_tr > 0 else ZERO
    denominator = plus_di + minus_di
    adx = D("100") * abs(plus_di - minus_di) / denominator if denominator > 0 else ZERO
    return recent_tr, previous_tr, plus_di, minus_di, adx


def _rsi(closes: Sequence[Decimal], length: int = 14) -> Decimal:
    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    if len(changes) < length:
        raise ValueError("insufficient closes for RSI")
    recent = changes[-length:]
    gains = sum((max(change, ZERO) for change in recent), ZERO) / D(str(length))
    losses = sum((max(-change, ZERO) for change in recent), ZERO) / D(str(length))
    if losses == 0:
        return D("100") if gains > 0 else D("50")
    return D("100") - D("100") / (ONE + gains / losses)


def _depth_features(depth: Mapping[str, object] | None) -> tuple[Decimal, Decimal, Decimal]:
    if not isinstance(depth, Mapping):
        return ZERO, ZERO, ZERO
    bids = depth.get("bids")
    asks = depth.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return ZERO, ZERO, ZERO
    try:
        best_bid = _decimal(bids[0][0], field="best bid")
        best_ask = _decimal(asks[0][0], field="best ask")
        midpoint = (best_bid + best_ask) / D("2")
        if midpoint <= 0 or best_ask < best_bid:
            raise ValueError("invalid spread")
        bid_quote = sum(
            (_decimal(row[0], field="bid price") * _decimal(row[1], field="bid qty") for row in bids[:20]),
            ZERO,
        )
        ask_quote = sum(
            (_decimal(row[0], field="ask price") * _decimal(row[1], field="ask qty") for row in asks[:20]),
            ZERO,
        )
        total = bid_quote + ask_quote
        imbalance = (bid_quote - ask_quote) / total if total > 0 else ZERO
        spread_bps = (best_ask - best_bid) / midpoint * D("10000")
        return spread_bps, imbalance, total
    except (ArithmeticError, IndexError, TypeError, ValueError):
        return ZERO, ZERO, ZERO


def trade_flow_from_agg_trades(
    trades: Sequence[Mapping[str, object]],
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[Decimal, bool]:
    """Return signed taker-volume imbalance for one fully closed interval."""
    buy_volume = ZERO
    sell_volume = ZERO
    accepted = 0
    for trade in trades:
        try:
            timestamp = int(trade.get("T", 0) or 0)
            quantity = _decimal(trade.get("q", "0"), field="aggregate trade qty")
            buyer_is_maker = bool(trade.get("m"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not start_ms <= timestamp <= end_ms or quantity <= 0:
            continue
        accepted += 1
        if buyer_is_maker:
            sell_volume += quantity
        else:
            buy_volume += quantity
    total = buy_volume + sell_volume
    if accepted == 0 or total <= 0:
        return ZERO, False
    return (buy_volume - sell_volume) / total, True


def build_prediction_features(
    klines: Sequence[Sequence[object]],
    *,
    as_of_ms: int,
    depth: Mapping[str, object] | None = None,
    trade_flow_imbalance: object = ZERO,
    trade_flow_available: bool = False,
    executor_panic_active: bool | None = None,
    executor_panic_hits: int | None = None,
) -> tuple[PredictionFeatures, list[PredictionBar]]:
    """Build deterministic TA features using data closed by ``as_of_ms``."""
    bars = parse_closed_klines(klines, as_of_ms=as_of_ms)
    if len(bars) < 60:
        raise ValueError("at least 60 closed one-minute bars are required")
    closes = [bar.close for bar in bars]
    price = closes[-1]
    ema20 = _ema(closes, 20)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd = [fast - slow for fast, slow in zip(ema12, ema26)]
    signal = _ema(macd, 9)
    atr, previous_atr, plus_di, minus_di, adx = _directional_indicators(bars)
    recent = bars[-20:]
    volume_total = sum((bar.volume for bar in recent), ZERO)
    vwap = (
        sum((bar.close * bar.volume for bar in recent), ZERO) / volume_total
        if volume_total > 0 else price
    )
    earlier_volume = sum((bar.volume for bar in bars[-40:-20]), ZERO) / D("20")
    recent_volume = volume_total / D("20")
    volume_ratio = recent_volume / earlier_volume if earlier_volume > 0 else ONE
    return_now = closes[-1] / closes[-2] - ONE
    return_previous = closes[-2] / closes[-3] - ONE
    ema_slope = ema20[-1] / ema20[-6] - ONE if ema20[-6] > 0 else ZERO
    ema_distance = price / ema20[-1] - ONE if ema20[-1] > 0 else ZERO
    atr_pct = atr / price if price > 0 else ZERO
    atr_change = atr / previous_atr - ONE if previous_atr > 0 else ZERO
    spread_bps, imbalance, depth_quote = _depth_features(depth)
    flow = _clamp(
        _decimal(trade_flow_imbalance, field="trade flow imbalance"), -ONE, ONE
    )
    panic_gap = max(D("2.5") * atr, price * D("0.0025"))
    if executor_panic_active is True:
        regime = "PANIC"
    elif price < ema20[-1] - panic_gap:
        regime = "PANIC"
    elif adx >= D("25"):
        regime = "TREND_UP" if plus_di >= minus_di else "TREND_DOWN"
    else:
        regime = "RANGE"
    features = PredictionFeatures(
        snapshot_ts_ms=int(as_of_ms),
        last_closed_bar_ts_ms=bars[-1].close_time_ms,
        price=price,
        ema_slope=ema_slope,
        ema_distance_pct=ema_distance,
        adx=adx,
        plus_di=plus_di,
        minus_di=minus_di,
        atr_pct=atr_pct,
        atr_change_pct=atr_change,
        vwap_deviation_pct=(price / vwap - ONE if vwap > 0 else ZERO),
        rsi=_rsi(closes),
        macd_histogram_pct=(macd[-1] - signal[-1]) / price,
        volume_ratio=volume_ratio,
        orderbook_imbalance=imbalance,
        orderbook_available=bool(depth),
        trade_flow_imbalance=flow,
        trade_flow_available=bool(trade_flow_available),
        spread_bps=spread_bps,
        depth_quote=depth_quote,
        acceleration=return_now - return_previous,
        executor_panic_active=executor_panic_active,
        executor_panic_hits=(
            max(0, int(executor_panic_hits))
            if executor_panic_hits is not None else None
        ),
        regime=regime,
    )
    return features, bars


def _sigmoid(value: Decimal) -> Decimal:
    bounded = _clamp(value, D("-12"), D("12"))
    result = 1.0 / (1.0 + math.exp(-float(bounded)))
    return D(str(result))


def _technical_prior(
    features: PredictionFeatures,
    plan: TradePlan,
    horizon_min: int,
) -> HorizonPrediction:
    atr = max(features.atr_pct, D("0.000001"))
    horizon_scale = D(str(math.sqrt(max(1, horizon_min))))
    directional = (
        features.ema_slope / atr * D("0.35")
        + features.ema_distance_pct / atr * D("0.20")
        + (features.plus_di - features.minus_di) / D("100") * D("1.2")
        + features.macd_histogram_pct / atr * D("0.35")
        + features.orderbook_imbalance * D("0.55")
        + features.trade_flow_imbalance * D("0.45")
        + features.acceleration / atr * D("0.20")
        - max(ZERO, (features.rsi - D("70")) / D("30")) * D("0.4")
        + max(ZERO, (D("30") - features.rsi) / D("30")) * D("0.25")
        - features.spread_bps / D("100")
    )
    if features.regime == "PANIC":
        directional -= D("1.5")
    elif features.regime == "TREND_DOWN":
        directional -= D("0.8")
    p_tp = _sigmoid(directional * horizon_scale / D("2"))
    distance = max(ZERO, features.price / plan.entry_price - ONE)
    fill_score = D("1.5") - distance / (atr * horizon_scale) * D("1.2")
    fill_score += (features.volume_ratio - ONE) * D("0.2")
    fill_score -= max(ZERO, directional) * D("0.15")
    p_fill = _sigmoid(fill_score)
    qty = plan.notional_quote / plan.entry_price
    round_trip_cost = (plan.fee_pct + plan.slippage_pct) * D("2")
    win = qty * (plan.take_profit_price - plan.entry_price) - plan.notional_quote * round_trip_cost
    loss = qty * (plan.stop_price - plan.entry_price) - plan.notional_quote * round_trip_cost
    expected = p_fill * (p_tp * win + (ONE - p_tp) * loss)
    adverse = atr * horizon_scale * (ONE + max(ZERO, -directional) / D("3"))
    time_to_fill = D(str(horizon_min * 60)) * _clamp(
        distance / (atr * horizon_scale), D("0.05"), ONE
    )
    return HorizonPrediction(
        horizon_min=horizon_min,
        probability_buy_fill=_clamp(p_fill, ZERO, ONE),
        probability_tp_before_stop=_clamp(p_tp, ZERO, ONE),
        expected_net_pnl_quote=expected,
        expected_mae_pct=adverse,
        expected_time_to_fill_sec=time_to_fill,
        samples=0,
        available=False,
    )


def predict_distribution(
    features: PredictionFeatures,
    plan: TradePlan,
    history: Sequence[ResolvedSample],
    *,
    min_samples: int = 60,
) -> tuple[HorizonPrediction, ...]:
    """Blend a TA prior with only chronologically eligible empirical outcomes."""
    output: list[HorizonPrediction] = []
    for horizon in HORIZONS_MIN:
        prior = _technical_prior(features, plan, horizon)
        rows = [
            sample for sample in history
            if sample.horizon_min == horizon
            and sample.regime == features.regime
            and sample.snapshot_ts_ms < features.snapshot_ts_ms
        ]
        count = len(rows)
        if not rows:
            output.append(prior)
            continue
        fill = D(str(sum(sample.outcome.buy_filled for sample in rows))) / D(str(count))
        tp_rows = [sample for sample in rows if sample.outcome.tp_before_stop is not None]
        tp = (
            D(str(sum(bool(sample.outcome.tp_before_stop) for sample in tp_rows)))
            / D(str(len(tp_rows))) if tp_rows else prior.probability_tp_before_stop
        )
        pnl = sum((sample.outcome.net_pnl_quote for sample in rows), ZERO) / D(str(count))
        mae = sum((sample.outcome.mae_pct for sample in rows), ZERO) / D(str(count))
        times = [sample.outcome.time_to_fill_sec for sample in rows if sample.outcome.time_to_fill_sec is not None]
        fill_time = (
            D(str(sum(times))) / D(str(len(times)))
            if times else prior.expected_time_to_fill_sec
        )
        empirical_weight = D(str(count)) / (D(str(count)) + D("30"))
        prior_weight = ONE - empirical_weight
        output.append(HorizonPrediction(
            horizon_min=horizon,
            probability_buy_fill=prior_weight * prior.probability_buy_fill + empirical_weight * fill,
            probability_tp_before_stop=prior_weight * prior.probability_tp_before_stop + empirical_weight * tp,
            expected_net_pnl_quote=prior_weight * prior.expected_net_pnl_quote + empirical_weight * pnl,
            expected_mae_pct=prior_weight * prior.expected_mae_pct + empirical_weight * mae,
            expected_time_to_fill_sec=prior_weight * prior.expected_time_to_fill_sec + empirical_weight * fill_time,
            samples=count,
            available=count >= min_samples,
        ))
    return tuple(output)


def evaluation_end_ms(snapshot_ts_ms: int, horizon_min: int) -> int:
    """Return the close of N complete one-minute bars after a decision.

    Decisions occur at arbitrary seconds. The first observable OHLC outcome is
    the close of the next full minute, not merely ``snapshot + 60 seconds``.
    """
    snapshot = int(snapshot_ts_ms)
    horizon = int(horizon_min)
    if snapshot < 0 or horizon <= 0:
        raise ValueError("snapshot and horizon must be positive")
    minute_start = snapshot - snapshot % 60_000
    return minute_start + (horizon + 1) * 60_000 - 1


def evaluate_plan(
    bars: Sequence[PredictionBar],
    *,
    snapshot_ts_ms: int,
    horizon_min: int,
    plan: TradePlan,
) -> PredictionOutcome | None:
    """Resolve fill/TP/STOP conservatively after the immutable decision time."""
    eligible_at = evaluation_end_ms(snapshot_ts_ms, horizon_min)
    future = [
        bar for bar in bars
        if snapshot_ts_ms < bar.open_time_ms and bar.close_time_ms <= eligible_at
    ]
    if not future or future[-1].close_time_ms < eligible_at - 60_000:
        return None
    fill_index: int | None = None
    for index, bar in enumerate(future):
        if bar.low <= plan.entry_price:
            fill_index = index
            break
    if fill_index is None:
        return PredictionOutcome(
            horizon_min, False, None, ZERO, ZERO, None, "NO_FILL", eligible_at
        )
    fill_bar = future[fill_index]
    qty = plan.notional_quote / plan.entry_price
    exit_price = future[-1].close
    exit_reason = "HORIZON"
    tp_before_stop: bool | None = None
    minimum = plan.entry_price
    for bar in future[fill_index:]:
        minimum = min(minimum, bar.low)
        stop_hit = bar.low <= plan.stop_price
        tp_hit = bar.high >= plan.take_profit_price
        if stop_hit:
            exit_price = plan.stop_price
            exit_reason = "STOP"
            tp_before_stop = False
            break
        if tp_hit:
            exit_price = plan.take_profit_price
            exit_reason = "TP"
            tp_before_stop = True
            break
    gross = qty * (exit_price - plan.entry_price)
    costs = plan.notional_quote * (plan.fee_pct + plan.slippage_pct) * D("2")
    return PredictionOutcome(
        horizon_min=horizon_min,
        buy_filled=True,
        tp_before_stop=tp_before_stop,
        net_pnl_quote=gross - costs,
        mae_pct=max(ZERO, ONE - minimum / plan.entry_price),
        # OHLC cannot reveal the instant within a bar. Using its close is the
        # conservative, reproducible estimate and never claims an early fill.
        time_to_fill_sec=max(0, (fill_bar.close_time_ms - snapshot_ts_ms) // 1000),
        exit_reason=exit_reason,
        resolved_at_ms=eligible_at,
    )


class PredictionShadowStore:
    """Durable, non-secret, immutable prediction and outcome journal."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS prediction_decisions (
                    decision_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    snapshot_ts_ms INTEGER NOT NULL,
                    feature_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    baseline_plan_json TEXT,
                    prediction_json TEXT NOT NULL,
                    algorithm_decision TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    UNIQUE(kind, symbol, snapshot_ts_ms, algorithm_decision)
                );
                CREATE TABLE IF NOT EXISTS prediction_outcomes (
                    decision_id TEXT NOT NULL,
                    horizon_min INTEGER NOT NULL,
                    eligible_at_ms INTEGER NOT NULL,
                    resolved_at_ms INTEGER,
                    outcome_json TEXT,
                    baseline_outcome_json TEXT,
                    terminal_reason TEXT,
                    expired_at_ms INTEGER,
                    PRIMARY KEY(decision_id, horizon_min),
                    FOREIGN KEY(decision_id) REFERENCES prediction_decisions(decision_id)
                );
                CREATE INDEX IF NOT EXISTS prediction_outcome_pending
                    ON prediction_outcomes(eligible_at_ms, resolved_at_ms);
            """)
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(prediction_outcomes)"
                )
            }
            if "terminal_reason" not in columns:
                connection.execute(
                    "ALTER TABLE prediction_outcomes "
                    "ADD COLUMN terminal_reason TEXT"
                )
            if "expired_at_ms" not in columns:
                connection.execute(
                    "ALTER TABLE prediction_outcomes "
                    "ADD COLUMN expired_at_ms INTEGER"
                )

    @staticmethod
    def _decision_id(
        kind: str, symbol: str, snapshot_ts_ms: int, algorithm_decision: str
    ) -> str:
        raw = f"{kind}:{symbol}:{snapshot_ts_ms}:{algorithm_decision}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def record(
        self,
        *,
        kind: str,
        symbol: str,
        features: PredictionFeatures,
        plan: TradePlan,
        predictions: Sequence[HorizonPrediction],
        algorithm_decision: str,
        baseline_plan: TradePlan | None = None,
    ) -> str:
        decision_id = self._decision_id(
            kind.upper(), symbol.upper(), features.snapshot_ts_ms, algorithm_decision
        )
        feature_json = json.dumps(_json_value(asdict(features)), sort_keys=True)
        plan_json = json.dumps(_json_value(asdict(plan)), sort_keys=True)
        baseline_json = (
            json.dumps(_json_value(asdict(baseline_plan)), sort_keys=True)
            if baseline_plan is not None else None
        )
        prediction_json = json.dumps(
            _json_value([asdict(item) for item in predictions]), sort_keys=True
        )
        now_ms = int(time.time() * 1000)
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO prediction_decisions
                   (decision_id,schema_version,kind,symbol,snapshot_ts_ms,
                    feature_json,plan_json,baseline_plan_json,prediction_json,
                    algorithm_decision,created_at_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id, PREDICTION_SCHEMA_VERSION, kind.upper(),
                    symbol.upper(), features.snapshot_ts_ms, feature_json,
                    plan_json, baseline_json, prediction_json,
                    algorithm_decision[:160], now_ms,
                ),
            )
            for horizon in HORIZONS_MIN:
                eligible_at = evaluation_end_ms(
                    features.snapshot_ts_ms, horizon
                )
                connection.execute(
                    """INSERT OR IGNORE INTO prediction_outcomes
                       (decision_id,horizon_min,eligible_at_ms)
                       VALUES (?,?,?)""",
                    (
                        decision_id,
                        horizon,
                        eligible_at,
                    ),
                )
        return decision_id

    @staticmethod
    def _plan(payload: str | None) -> TradePlan | None:
        if not payload:
            return None
        raw = json.loads(payload)
        return TradePlan(**{
            name: _decimal(raw[name], field=name)
            for name in (
                "entry_price", "take_profit_price", "stop_price",
                "notional_quote", "fee_pct", "slippage_pct",
            )
        })

    def settle(
        self,
        symbol: str,
        bars: Sequence[PredictionBar],
        *,
        as_of_ms: int,
    ) -> int:
        ordered_bars = sorted(bars, key=lambda item: item.open_time_ms)
        earliest_close_ms = (
            int(ordered_bars[0].close_time_ms) if ordered_bars else None
        )
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT o.decision_id,o.horizon_min,d.snapshot_ts_ms,
                          d.plan_json,d.baseline_plan_json
                   FROM prediction_outcomes o
                   JOIN prediction_decisions d ON d.decision_id=o.decision_id
                   WHERE d.symbol=? AND o.resolved_at_ms IS NULL
                     AND o.eligible_at_ms<=?
                   ORDER BY o.eligible_at_ms LIMIT 500""",
                (symbol.upper(), as_of_ms),
            ).fetchall()
            settled = 0
            for decision_id, horizon, snapshot, plan_json, baseline_json in rows:
                required_start_close = evaluation_end_ms(int(snapshot), 1)
                if (
                    earliest_close_ms is not None
                    and required_start_close < earliest_close_ms
                ):
                    connection.execute(
                        """UPDATE prediction_outcomes
                           SET resolved_at_ms=?,expired_at_ms=?,
                               terminal_reason='INSUFFICIENT_HISTORY'
                           WHERE decision_id=? AND horizon_min=?
                             AND resolved_at_ms IS NULL""",
                        (
                            int(as_of_ms),
                            int(as_of_ms),
                            decision_id,
                            int(horizon),
                        ),
                    )
                    settled += 1
                    continue
                plan = self._plan(plan_json)
                baseline = self._plan(baseline_json)
                if plan is None:
                    continue
                outcome = evaluate_plan(
                    bars,
                    snapshot_ts_ms=int(snapshot),
                    horizon_min=int(horizon),
                    plan=plan,
                )
                baseline_outcome = (
                    evaluate_plan(
                        bars,
                        snapshot_ts_ms=int(snapshot),
                        horizon_min=int(horizon),
                        plan=baseline,
                    )
                    if baseline is not None else None
                )
                if outcome is None or (baseline is not None and baseline_outcome is None):
                    continue
                connection.execute(
                    """UPDATE prediction_outcomes
                       SET resolved_at_ms=?,outcome_json=?,baseline_outcome_json=?,
                           terminal_reason='RESOLVED'
                       WHERE decision_id=? AND horizon_min=?""",
                    (
                        int(outcome.resolved_at_ms),
                        json.dumps(_json_value(asdict(outcome)), sort_keys=True),
                        (
                            json.dumps(_json_value(asdict(baseline_outcome)), sort_keys=True)
                            if baseline_outcome is not None else None
                        ),
                        decision_id,
                        int(horizon),
                    ),
                )
                settled += 1
        return settled

    def reanchor_performance(self, symbol: str) -> dict[str, object]:
        """Summarize counterfactual value without enabling APPLY."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT d.feature_json,d.plan_json,o.horizon_min,
                          o.outcome_json,o.baseline_outcome_json
                   FROM prediction_decisions d
                   JOIN prediction_outcomes o ON o.decision_id=d.decision_id
                   WHERE d.symbol=? AND d.kind='REANCHOR'
                     AND o.outcome_json IS NOT NULL""",
                (symbol.upper(),),
            ).fetchall()
        filled = 0
        tp = 0
        net = ZERO
        baseline_net = ZERO
        gaps: list[Decimal] = []
        for feature_json, plan_json, _horizon, outcome_json, baseline_json in rows:
            outcome = self._outcome(outcome_json)
            baseline = (
                self._outcome(baseline_json)
                if baseline_json else outcome
            )
            filled += int(outcome.buy_filled)
            tp += int(outcome.tp_before_stop is True)
            net += outcome.net_pnl_quote
            baseline_net += baseline.net_pnl_quote
            try:
                feature = json.loads(feature_json)
                plan = json.loads(plan_json)
                market = _decimal(
                    feature["current_price"], field="current price"
                )
                entry = _decimal(plan["entry_price"], field="entry price")
                if market > 0:
                    gaps.append((market - entry) / market)
            except (
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                continue
        count = len(rows)
        mean_gap = (
            sum(gaps, ZERO) / D(str(len(gaps))) if gaps else ZERO
        )
        return {
            "resolved": count,
            "buy_filled": filled,
            "tp_before_stop": tp,
            "net_pnl_quote": str(net),
            "baseline_net_pnl_quote": str(baseline_net),
            "net_edge_quote": str(net - baseline_net),
            "mean_entry_gap_pct": str(mean_gap),
        }

    @staticmethod
    def _outcome(payload: str) -> PredictionOutcome:
        raw = json.loads(payload)
        return PredictionOutcome(
            horizon_min=int(raw["horizon_min"]),
            buy_filled=bool(raw["buy_filled"]),
            tp_before_stop=raw.get("tp_before_stop"),
            net_pnl_quote=_decimal(raw["net_pnl_quote"], field="net pnl"),
            mae_pct=_decimal(raw["mae_pct"], field="mae"),
            time_to_fill_sec=(
                int(raw["time_to_fill_sec"])
                if raw.get("time_to_fill_sec") is not None else None
            ),
            exit_reason=str(raw["exit_reason"]),
            resolved_at_ms=int(raw["resolved_at_ms"]),
        )

    def resolved_samples(
        self,
        symbol: str,
        *,
        before_ts_ms: int | None = None,
        kind: str = "STRATEGY",
    ) -> list[ResolvedSample]:
        query = """SELECT d.snapshot_ts_ms,d.feature_json,o.horizon_min,
                          o.outcome_json,o.baseline_outcome_json
                   FROM prediction_decisions d
                   JOIN prediction_outcomes o ON o.decision_id=d.decision_id
                   WHERE d.symbol=? AND d.kind=? AND o.outcome_json IS NOT NULL"""
        params: list[object] = [symbol.upper(), kind.upper()]
        if before_ts_ms is not None:
            query += " AND o.resolved_at_ms<=?"
            params.append(int(before_ts_ms))
        query += " ORDER BY d.snapshot_ts_ms,o.horizon_min"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        output = []
        for snapshot, feature_json, horizon, outcome_json, baseline_json in rows:
            features = json.loads(feature_json)
            outcome = self._outcome(outcome_json)
            baseline = self._outcome(baseline_json) if baseline_json else outcome
            output.append(ResolvedSample(
                snapshot_ts_ms=int(snapshot),
                regime=str(features.get("regime", "UNKNOWN")),
                horizon_min=int(horizon),
                outcome=outcome,
                baseline_net_pnl_quote=baseline.net_pnl_quote,
            ))
        return output

    def summary(self, symbol: str) -> dict[str, object]:
        with self._connect() as connection:
            decisions = connection.execute(
                "SELECT COUNT(*) FROM prediction_decisions WHERE symbol=?",
                (symbol.upper(),),
            ).fetchone()[0]
            resolved = connection.execute(
                """SELECT COUNT(*) FROM prediction_outcomes o
                   JOIN prediction_decisions d ON d.decision_id=o.decision_id
                   WHERE d.symbol=? AND o.outcome_json IS NOT NULL""",
                (symbol.upper(),),
            ).fetchone()[0]
            counterfactuals = connection.execute(
                """SELECT COUNT(*) FROM prediction_decisions
                   WHERE symbol=? AND kind='REANCHOR'""",
                (symbol.upper(),),
            ).fetchone()[0]
            pending = connection.execute(
                """SELECT COUNT(*) FROM prediction_outcomes o
                   JOIN prediction_decisions d ON d.decision_id=o.decision_id
                   WHERE d.symbol=? AND o.resolved_at_ms IS NULL""",
                (symbol.upper(),),
            ).fetchone()[0]
            expired = connection.execute(
                """SELECT COUNT(*) FROM prediction_outcomes o
                   JOIN prediction_decisions d ON d.decision_id=o.decision_id
                   WHERE d.symbol=? AND
                         o.terminal_reason='INSUFFICIENT_HISTORY'""",
                (symbol.upper(),),
            ).fetchone()[0]
        return {
            "decisions": int(decisions),
            "resolved_outcomes": int(resolved),
            "pending_outcomes": int(pending),
            "expired_outcomes": int(expired),
            "reanchor_counterfactuals": int(counterfactuals),
            "reanchor_performance": self.reanchor_performance(symbol),
        }


def _bootstrap_ci(
    values: Sequence[Decimal], *, iterations: int = 1000, seed: int = 23
) -> tuple[Decimal, Decimal]:
    if not values:
        return ZERO, ZERO
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        draw = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(draw, ZERO) / D(str(len(draw))))
    means.sort()
    return means[int(len(means) * 0.025)], means[int(len(means) * 0.975)]


def _paired_sign_p_value(edges: Sequence[Decimal]) -> float:
    nonzero = [value for value in edges if value != 0]
    if not nonzero:
        return 1.0
    wins = sum(value > 0 for value in nonzero)
    probability = sum(
        math.comb(len(nonzero), index) for index in range(wins, len(nonzero) + 1)
    ) / (2 ** len(nonzero))
    return min(1.0, probability)


def _holm(p_values: Sequence[float], alpha: float = 0.05) -> list[bool]:
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    accepted = [False] * len(p_values)
    for rank, (index, value) in enumerate(indexed):
        if value <= alpha / max(1, len(indexed) - rank):
            accepted[index] = True
        else:
            break
    return accepted


def prediction_apply_gate(
    samples: Sequence[ResolvedSample],
    *,
    min_independent_samples: int = 120,
    min_regime_samples: int = 20,
    min_fill_rate: Decimal = D("0.10"),
    max_drawdown_quote: Decimal = D("25"),
) -> dict[str, object]:
    """Approve nothing unless net edge survives CI, Holm and every regime."""
    ordered = sorted(samples, key=lambda item: (item.snapshot_ts_ms, item.horizon_min))
    grouped: dict[int, list[ResolvedSample]] = {}
    for item in ordered:
        grouped.setdefault(item.snapshot_ts_ms, []).append(item)
    independent_rows = []
    for timestamp, rows in sorted(grouped.items()):
        count = D(str(len(rows)))
        independent_rows.append({
            "timestamp": timestamp,
            "regime": rows[0].regime,
            "pnl": sum(
                (row.outcome.net_pnl_quote for row in rows), ZERO
            ) / count,
            "edge": sum(
                (
                    row.outcome.net_pnl_quote
                    - row.baseline_net_pnl_quote
                    for row in rows
                ),
                ZERO,
            ) / count,
            "fill": D(str(sum(row.outcome.buy_filled for row in rows)))
            / count,
        })
    independent = len(independent_rows)
    pnl = [row["pnl"] for row in independent_rows]
    edges = [row["edge"] for row in independent_rows]
    ci = _bootstrap_ci(pnl)
    edge_ci = _bootstrap_ci(edges)
    hypotheses: list[tuple[str, list[Decimal]]] = []
    for horizon in HORIZONS_MIN:
        horizon_rows = [
            row for row in ordered if row.horizon_min == horizon
        ]
        hypotheses.append((
            f"horizon_{horizon}",
            [
                row.outcome.net_pnl_quote - row.baseline_net_pnl_quote
                for row in horizon_rows
            ],
        ))
    regimes = sorted({str(row["regime"]) for row in independent_rows})
    for regime in regimes:
        hypotheses.append((
            f"regime_{regime}",
            [
                row["edge"]
                for row in independent_rows
                if row["regime"] == regime
            ],
        ))
    p_values = [
        _paired_sign_p_value(hypothesis_edges)
        for _, hypothesis_edges in hypotheses
    ]
    holm = _holm(p_values)
    hypothesis_report = {
        name: {
            "samples": len(hypothesis_edges),
            "p_value": p_values[index],
            "passed": holm[index],
        }
        for index, (name, hypothesis_edges) in enumerate(hypotheses)
    }
    cumulative = ZERO
    peak = ZERO
    max_drawdown = ZERO
    for value in pnl:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    fill_rate = (
        sum((row["fill"] for row in independent_rows), ZERO)
        / D(str(independent))
        if independent_rows else ZERO
    )
    required_regimes = {"TREND_UP", "TREND_DOWN", "RANGE", "PANIC"}
    regime_counts = {
        regime: sum(row["regime"] == regime for row in independent_rows)
        for regime in required_regimes
    }
    reasons = []
    if independent < min_independent_samples:
        reasons.append("insufficient independent samples")
    if ci[0] <= 0:
        reasons.append("net expectancy lower CI is not positive")
    if edge_ci[0] <= 0:
        reasons.append("baseline edge lower CI is not positive")
    if any(count < min_regime_samples for count in regime_counts.values()):
        reasons.append("market regime coverage is incomplete")
    if hypotheses and not all(holm):
        reasons.append("Holm-corrected hypotheses did not all pass")
    if fill_rate < min_fill_rate:
        reasons.append("fill rate is below threshold")
    if max_drawdown > max_drawdown_quote:
        reasons.append("drawdown exceeds threshold")
    return {
        "approved": not reasons,
        "mode": "APPLY" if not reasons else "SHADOW",
        "reasons": reasons,
        "independent_samples": independent,
        "net_expectancy_ci": [format(ci[0], "f"), format(ci[1], "f")],
        "baseline_edge_ci": [format(edge_ci[0], "f"), format(edge_ci[1], "f")],
        "fill_rate": format(fill_rate, "f"),
        "max_drawdown_quote": format(max_drawdown, "f"),
        "regime_counts": regime_counts,
        "hypotheses": hypothesis_report,
    }


def walk_forward_prediction_report(
    samples: Sequence[ResolvedSample],
    *,
    min_train_samples: int = 60,
) -> dict[str, object]:
    """Evaluate chronologically; a sample can train only later timestamps."""
    ordered = sorted(samples, key=lambda item: (item.snapshot_ts_ms, item.horizon_min))
    evaluated = []
    for index, sample in enumerate(ordered):
        train = [row for row in ordered[:index] if row.snapshot_ts_ms < sample.snapshot_ts_ms]
        if len(train) < min_train_samples:
            continue
        evaluated.append({
            "snapshot_ts_ms": sample.snapshot_ts_ms,
            "horizon_min": sample.horizon_min,
            "train_max_ts_ms": max(row.snapshot_ts_ms for row in train),
            "actual_net_pnl_quote": format(sample.outcome.net_pnl_quote, "f"),
            "baseline_net_pnl_quote": format(sample.baseline_net_pnl_quote, "f"),
        })
    return {
        "schema_version": PREDICTION_SCHEMA_VERSION,
        "method": "expanding-window-walk-forward",
        "lookahead": False,
        "evaluated": evaluated,
        "gate": prediction_apply_gate(ordered),
    }
