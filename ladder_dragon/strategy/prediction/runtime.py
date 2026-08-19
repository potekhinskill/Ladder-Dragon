# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: build look-ahead-safe technical predictions and SHADOW outcomes.
"""Chronological technical prediction and counterfactual SHADOW accounting.

The module has no exchange or order capability.  Runtime callers provide closed
bars and sanitized L2 aggregates; every decision is immutable and outcomes are
eligible only after their horizon has elapsed.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Iterable, Mapping, Sequence

from ladder_dragon.strategy.prediction.models import (
    HorizonPrediction,
    PredictionBar,
    PredictionFeatures,
    PredictionOutcome,
    ResolvedSample,
    TradePlan, decision_metadata, trade_plan_fee_fields,
)

D = Decimal
ZERO = D("0")
ONE = D("1")
HORIZONS_MIN = (1, 5, 15)
PREDICTION_SCHEMA_VERSION = 2
MAX_RESOLVED_DECISIONS = 1_000
MAX_PERFORMANCE_DECISIONS = 10_000
EVIDENCE_ROLES = frozenset({"SELECTION", "CONFIRMATION", "DIAGNOSTIC", "LEGACY"})


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


def _validated_horizons(horizons_min: Sequence[int]) -> tuple[int, ...]:
    horizons = tuple(horizons_min)
    invalid_type = any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in horizons
    )
    if (
        not horizons
        or invalid_type
        or any(value <= 0 for value in horizons)
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise ValueError("prediction horizons must be unique increasing positive integers")
    return horizons


def predict_distribution(
    features: PredictionFeatures,
    plan: TradePlan,
    history: Sequence[ResolvedSample],
    *,
    min_samples: int = 60,
    horizons_min: Sequence[int] = HORIZONS_MIN,
) -> tuple[HorizonPrediction, ...]:
    """Blend a TA prior with only chronologically eligible empirical outcomes."""
    horizons = _validated_horizons(horizons_min)
    if not plan.entry_enabled:
        return tuple(
            HorizonPrediction(horizon, ZERO, ZERO, ZERO, ZERO, ZERO, 0, True)
            for horizon in horizons
        )
    output: list[HorizonPrediction] = []
    for horizon in horizons:
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
    if not plan.entry_enabled:
        return PredictionOutcome(
            horizon_min, False, None, ZERO, ZERO, None, "NO_TRADE", eligible_at
        )
    entry_deadline_ms = (
        snapshot_ts_ms + plan.entry_ttl_sec * 1000
        if plan.entry_ttl_sec is not None else None
    )
    fill_index: int | None = None
    for index, bar in enumerate(future):
        if entry_deadline_ms is not None and bar.close_time_ms > entry_deadline_ms:
            break
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
        """Create versioned SHADOW tables without deleting historical evidence."""
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
                    source_sha256 TEXT,
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
            if "source_sha256" not in columns:
                connection.execute(
                    "ALTER TABLE prediction_outcomes "
                    "ADD COLUMN source_sha256 TEXT"
                )
            from ladder_dragon.strategy.prediction.experiment_lifecycle import (
                migrate_experiment_lifecycle,
            )
            migrate_experiment_lifecycle(connection)

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
        horizons_min: Sequence[int] = HORIZONS_MIN,
        experiment_id: str | None = None,
        evidence_role: str = "LEGACY",
        candidate_fingerprint: str | None = None,
        baseline_fingerprint: str | None = None,
    ) -> str:
        """Persist one immutable forecast and its untouched baseline plan."""
        horizons = _validated_horizons(horizons_min)
        if tuple(item.horizon_min for item in predictions) != horizons:
            raise ValueError("prediction horizons do not match outcome horizons")
        normalized_kind = kind.upper()
        experimental = normalized_kind.startswith("EXPERIMENT_")
        control = normalized_kind.startswith("CONTROL_")
        if (
            normalized_kind not in {"STRATEGY", "REANCHOR"} and not experimental
            and not control
        ):
            raise ValueError("unsupported prediction kind")
        if normalized_kind == "REANCHOR" and baseline_plan is None:
            raise ValueError("REANCHOR requires the original order baseline")
        if (experimental or control) and baseline_plan is None:
            raise ValueError("counterfactual kind requires an explicit baseline")
        role = str(evidence_role).strip().upper()
        if role not in EVIDENCE_ROLES:
            raise ValueError("unsupported prediction evidence role")
        normalized_experiment_id = (
            str(experiment_id).strip() if experiment_id is not None else None
        )
        if role != "LEGACY" and not normalized_experiment_id:
            raise ValueError("non-legacy evidence requires experiment_id")
        if role == "LEGACY" and normalized_experiment_id:
            raise ValueError("legacy evidence cannot have experiment_id")
        fingerprints = (candidate_fingerprint, baseline_fingerprint)
        if role != "LEGACY" and any(
            not isinstance(value, str) or len(value) != 64
            for value in fingerprints
        ):
            raise ValueError("classified evidence requires SHA-256 fingerprints")
        decision_id = self._decision_id(
            normalized_kind,
            symbol.upper(),
            features.snapshot_ts_ms,
            f"{algorithm_decision}:{normalized_experiment_id or ''}:{role}",
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
                    algorithm_decision,created_at_ms,experiment_id,evidence_role,
                    candidate_fingerprint,baseline_fingerprint)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id, PREDICTION_SCHEMA_VERSION, normalized_kind,
                    symbol.upper(), features.snapshot_ts_ms, feature_json,
                    plan_json, baseline_json, prediction_json,
                    algorithm_decision, now_ms,
                    normalized_experiment_id, role,
                    candidate_fingerprint, baseline_fingerprint,
                ),
            )
            for horizon in horizons:
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
        values = {
            name: _decimal(raw[name], field=name)
            for name in (
                "entry_price", "take_profit_price", "stop_price",
                "notional_quote", "fee_pct", "slippage_pct",
            )
        }
        entry_enabled = raw.get("entry_enabled", True)
        if not isinstance(entry_enabled, bool):
            raise ValueError("entry_enabled must be boolean")
        entry_ttl = raw.get("entry_ttl_sec")
        if entry_ttl is not None and (
            isinstance(entry_ttl, bool) or not isinstance(entry_ttl, int)
        ):
            raise ValueError("entry_ttl_sec must be an integer")
        return TradePlan(
            **values,
            entry_ttl_sec=entry_ttl,
            entry_enabled=entry_enabled,
            **trade_plan_fee_fields(raw),
        )

    def settle(
        self,
        symbol: str,
        bars: Sequence[PredictionBar],
        *,
        as_of_ms: int,
    ) -> int:
        """Resolve only horizons fully elapsed at the supplied decision time."""
        ordered_bars = sorted(bars, key=lambda item: item.open_time_ms)
        earliest_close_ms = (
            int(ordered_bars[0].close_time_ms) if ordered_bars else None
        )
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT o.decision_id,o.horizon_min,d.snapshot_ts_ms,d.kind,
                          d.plan_json,d.baseline_plan_json
                   FROM prediction_outcomes o
                   JOIN prediction_decisions d ON d.decision_id=o.decision_id
                   WHERE d.symbol=? AND o.resolved_at_ms IS NULL
                     AND o.eligible_at_ms<=?
                   ORDER BY o.eligible_at_ms LIMIT 500""",
                (symbol.upper(), as_of_ms),
            ).fetchall()
            settled = 0
            for (
                decision_id,
                horizon,
                snapshot,
                kind,
                plan_json,
                baseline_json,
            ) in rows:
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
                if baseline_outcome is None and str(kind).upper() == "STRATEGY":
                    baseline_outcome = self._no_trade_outcome(outcome)
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

    def backfill_expired(
        self,
        symbol: str,
        bars: Sequence[PredictionBar],
        *,
        source_sha256: str,
        as_of_ms: int | None = None,
    ) -> int:
        """Recover expired outcomes only from complete, source-hashed minutes."""
        source = str(source_sha256).lower()
        if len(source) != 64 or any(ch not in "0123456789abcdef" for ch in source):
            raise ValueError("source_sha256 must be a lowercase SHA-256")
        ordered = sorted(bars, key=lambda item: item.open_time_ms)
        by_open = {int(item.open_time_ms): item for item in ordered}
        cutoff = int(as_of_ms) if as_of_ms is not None else (
            max((item.close_time_ms for item in ordered), default=-1)
        )
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT o.decision_id,o.horizon_min,d.snapshot_ts_ms,d.kind,
                          d.plan_json,d.baseline_plan_json,o.eligible_at_ms
                   FROM prediction_outcomes o
                   JOIN prediction_decisions d ON d.decision_id=o.decision_id
                   WHERE d.symbol=?
                     AND o.terminal_reason='INSUFFICIENT_HISTORY'
                     AND o.outcome_json IS NULL
                     AND o.eligible_at_ms<=?
                   ORDER BY o.eligible_at_ms""",
                (symbol.upper(), cutoff),
            ).fetchall()
            recovered = 0
            for (
                decision_id,
                horizon,
                snapshot,
                kind,
                plan_json,
                baseline_json,
                eligible,
            ) in rows:
                first_open = (int(snapshot) // 60_000 + 1) * 60_000
                expected_opens = [
                    first_open + offset * 60_000
                    for offset in range(int(horizon))
                ]
                window = [by_open.get(open_time) for open_time in expected_opens]
                if any(item is None for item in window):
                    continue
                complete = [item for item in window if item is not None]
                if any(
                    item.close_time_ms != item.open_time_ms + 59_999
                    or item.close_time_ms > int(eligible)
                    for item in complete
                ):
                    continue
                plan = self._plan(plan_json)
                baseline = self._plan(baseline_json)
                if plan is None:
                    continue
                outcome = evaluate_plan(
                    complete,
                    snapshot_ts_ms=int(snapshot),
                    horizon_min=int(horizon),
                    plan=plan,
                )
                baseline_outcome = (
                    evaluate_plan(
                        complete,
                        snapshot_ts_ms=int(snapshot),
                        horizon_min=int(horizon),
                        plan=baseline,
                    )
                    if baseline is not None else None
                )
                if outcome is None or (
                    baseline is not None and baseline_outcome is None
                ):
                    continue
                if baseline_outcome is None and str(kind).upper() == "STRATEGY":
                    baseline_outcome = self._no_trade_outcome(outcome)
                connection.execute(
                    """UPDATE prediction_outcomes
                       SET resolved_at_ms=?,outcome_json=?,
                           baseline_outcome_json=?,
                           terminal_reason='BACKFILLED',
                           source_sha256=?
                       WHERE decision_id=? AND horizon_min=?
                         AND terminal_reason='INSUFFICIENT_HISTORY'
                         AND outcome_json IS NULL""",
                    (
                        int(outcome.resolved_at_ms),
                        json.dumps(_json_value(asdict(outcome)), sort_keys=True),
                        (
                            json.dumps(
                                _json_value(asdict(baseline_outcome)),
                                sort_keys=True,
                            )
                            if baseline_outcome is not None else None
                        ),
                        source,
                        decision_id,
                        int(horizon),
                    ),
                )
                recovered += 1
        return recovered

    def reanchor_performance(self, symbol: str) -> dict[str, object]:
        """Summarize counterfactual value without enabling APPLY."""
        with self._connect() as connection:
            rows = connection.execute(
                """WITH recent AS (
                       SELECT decision_id,feature_json,plan_json
                       FROM prediction_decisions
                       WHERE symbol=? AND kind='REANCHOR'
                       ORDER BY rowid DESC
                       LIMIT ?
                   )
                   SELECT d.feature_json,d.plan_json,o.horizon_min,
                          o.outcome_json,o.baseline_outcome_json
                   FROM recent d
                   JOIN prediction_outcomes o ON o.decision_id=d.decision_id
                   WHERE o.outcome_json IS NOT NULL""",
                (symbol.upper(), MAX_PERFORMANCE_DECISIONS),
            )
            filled = 0
            tp = 0
            net = ZERO
            baseline_net = ZERO
            gaps: list[Decimal] = []
            missing_baselines = 0
            row_count = 0
            for feature_json, plan_json, _horizon, outcome_json, baseline_json in rows:
                row_count += 1
                outcome = self._outcome(outcome_json)
                if not baseline_json:
                    missing_baselines += 1
                    continue
                baseline = self._outcome(baseline_json)
                filled += int(outcome.buy_filled)
                tp += int(outcome.tp_before_stop is True)
                net += outcome.net_pnl_quote
                baseline_net += baseline.net_pnl_quote
                try:
                    feature = json.loads(feature_json)
                    plan = json.loads(plan_json)
                    market = _decimal(
                        feature.get("price", feature.get("current_price")),
                        field="current price",
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
        count = row_count - missing_baselines
        mean_gap = (
            sum(gaps, ZERO) / D(str(len(gaps))) if gaps else ZERO
        )
        return {
            "resolved": count,
            "missing_baselines": missing_baselines,
            "buy_filled": filled,
            "tp_before_stop": tp,
            "net_pnl_quote": str(net),
            "baseline_net_pnl_quote": str(baseline_net),
            "net_edge_quote": str(net - baseline_net),
            "mean_entry_gap_pct": str(mean_gap),
            "maximum_decisions": MAX_PERFORMANCE_DECISIONS,
        }

    def regime_performance(
        self,
        symbol: str,
        *,
        minimum_samples_per_regime: int = 30,
    ) -> dict[str, object]:
        """Compare BUY distance, PANIC and re-anchor outcomes by market regime."""
        minimum = max(1, int(minimum_samples_per_regime))
        with self._connect() as connection:
            rows = connection.execute(
                """WITH recent AS (
                       SELECT decision_id,kind,feature_json,plan_json
                       FROM prediction_decisions
                       WHERE symbol=?
                       ORDER BY rowid DESC
                       LIMIT ?
                   )
                   SELECT d.kind,d.feature_json,d.plan_json,o.outcome_json,
                          o.baseline_outcome_json
                   FROM recent d
                   JOIN prediction_outcomes o ON o.decision_id=d.decision_id
                   WHERE o.outcome_json IS NOT NULL""",
                (symbol.upper(), MAX_PERFORMANCE_DECISIONS),
            )
            buckets: dict[tuple[str, str, str], dict[str, object]] = {}
            for kind, feature_json, plan_json, outcome_json, baseline_json in rows:
                try:
                    features = json.loads(feature_json)
                    plan = json.loads(plan_json)
                    outcome = self._outcome(outcome_json)
                    baseline = self._baseline_outcome(
                        str(kind), baseline_json, outcome
                    )
                    regime = str(features.get("regime") or "UNKNOWN").upper()
                    panic = features.get("executor_panic_active")
                    panic_label = (
                        "ACTIVE" if panic is True
                        else "INACTIVE" if panic is False
                        else "UNKNOWN"
                    )
                    price = _decimal(
                        features.get("price", features.get("current_price")),
                        field="feature price",
                    )
                    entry = _decimal(plan["entry_price"], field="entry price")
                    gap = max(ZERO, (price - entry) / price) if price > 0 else ZERO
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ):
                    continue
                key = (regime, str(kind).upper(), panic_label)
                bucket = buckets.setdefault(key, {
                    "samples": 0,
                    "fills": 0,
                    "tp_before_stop": 0,
                    "net": ZERO,
                    "baseline_net": ZERO,
                    "mae": ZERO,
                    "entry_gap": ZERO,
                })
                bucket["samples"] = int(bucket["samples"]) + 1
                bucket["fills"] = int(bucket["fills"]) + int(outcome.buy_filled)
                bucket["tp_before_stop"] = (
                    int(bucket["tp_before_stop"])
                    + int(outcome.tp_before_stop is True)
                )
                bucket["net"] = bucket["net"] + outcome.net_pnl_quote
                bucket["baseline_net"] = (
                    bucket["baseline_net"] + baseline.net_pnl_quote
                )
                bucket["mae"] = bucket["mae"] + outcome.mae_pct
                bucket["entry_gap"] = bucket["entry_gap"] + gap

        groups = []
        observed_regimes: set[str] = set()
        sufficient_regimes: set[str] = set()
        for (regime, kind, panic), bucket in sorted(buckets.items()):
            samples = int(bucket["samples"])
            observed_regimes.add(regime)
            if samples >= minimum:
                sufficient_regimes.add(regime)
            divisor = D(str(samples))
            groups.append({
                "regime": regime,
                "kind": kind,
                "panic": panic,
                "samples": samples,
                "fill_rate": format(D(str(bucket["fills"])) / divisor, "f"),
                "tp_rate": format(
                    D(str(bucket["tp_before_stop"])) / divisor, "f"
                ),
                "mean_net_pnl_quote": format(bucket["net"] / divisor, "f"),
                "mean_baseline_edge_quote": format(
                    (bucket["net"] - bucket["baseline_net"]) / divisor, "f"
                ),
                "mean_mae_pct": format(bucket["mae"] / divisor, "f"),
                "mean_buy_distance_pct": format(
                    bucket["entry_gap"] / divisor, "f"
                ),
            })
        required_regimes = {"TREND_UP", "TREND_DOWN", "RANGE", "PANIC"}
        return {
            "symbol": symbol.upper(),
            "minimum_samples_per_regime": minimum,
            "maximum_decisions": MAX_PERFORMANCE_DECISIONS,
            "groups": groups,
            "observed_regimes": sorted(observed_regimes),
            "missing_or_insufficient_regimes": sorted(
                required_regimes - sufficient_regimes
            ),
            "statistically_sufficient": required_regimes <= sufficient_regimes,
            # Reporting code can never promote SHADOW to APPLY.
            "apply_allowed": False,
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

    @staticmethod
    def _no_trade_outcome(outcome: PredictionOutcome) -> PredictionOutcome:
        """Return the explicit USDT/no-entry baseline for STRATEGY evidence."""
        return PredictionOutcome(
            horizon_min=outcome.horizon_min,
            buy_filled=False,
            tp_before_stop=None,
            net_pnl_quote=ZERO,
            mae_pct=ZERO,
            time_to_fill_sec=None,
            exit_reason="NO_TRADE",
            resolved_at_ms=outcome.resolved_at_ms,
        )

    @classmethod
    def _baseline_outcome(
        cls,
        kind: str,
        payload: str | None,
        outcome: PredictionOutcome,
    ) -> PredictionOutcome:
        if payload:
            return cls._outcome(payload)
        if str(kind).upper() == "STRATEGY":
            return cls._no_trade_outcome(outcome)
        raise ValueError("counterfactual baseline outcome is missing")

    def resolved_samples(
        self,
        symbol: str,
        *,
        before_ts_ms: int | None = None,
        kind: str = "STRATEGY",
        experiment_id: str | None = None,
        evidence_role: str | None = None,
    ) -> list[ResolvedSample]:
        query = """WITH recent AS (
                       SELECT decision_id,snapshot_ts_ms,feature_json,algorithm_decision
                       FROM prediction_decisions
                       WHERE symbol=? AND kind=?"""
        normalized_kind = kind.upper()
        params: list[object] = [symbol.upper(), normalized_kind]
        if experiment_id is not None:
            query += " AND experiment_id=?"
            params.append(str(experiment_id))
        if evidence_role is not None:
            role = str(evidence_role).upper()
            if role not in EVIDENCE_ROLES:
                raise ValueError("unsupported prediction evidence role")
            query += " AND evidence_role=?"
            params.append(role)
        if before_ts_ms is not None:
            query += " AND snapshot_ts_ms<=?"
            params.append(int(before_ts_ms))
        # Decisions are immutable and append-only. The rowid walk avoids a
        # temporary sort that can exceed the Raspberry Pi tmpfs capacity.
        query += """ ORDER BY rowid DESC
                       LIMIT ?
                   )
                   SELECT d.snapshot_ts_ms,d.feature_json,d.algorithm_decision,
                          o.horizon_min,o.outcome_json,o.baseline_outcome_json
                   FROM recent d
                   JOIN prediction_outcomes o ON o.decision_id=d.decision_id
                   WHERE o.outcome_json IS NOT NULL"""
        params.append(MAX_RESOLVED_DECISIONS)
        if before_ts_ms is not None:
            query += " AND o.resolved_at_ms<=?"
            params.append(int(before_ts_ms))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        output = []
        for snapshot, feature_json, decision, horizon, outcome_json, baseline_json in rows:
            features = json.loads(feature_json)
            outcome = self._outcome(outcome_json)
            baseline = self._baseline_outcome(
                normalized_kind, baseline_json, outcome
            )
            output.append(ResolvedSample(
                snapshot_ts_ms=int(snapshot),
                regime=str(features.get("regime", "UNKNOWN")),
                horizon_min=int(horizon),
                outcome=outcome,
                baseline_net_pnl_quote=baseline.net_pnl_quote,
                decision_metadata=decision_metadata(str(decision)),
            ))
        return sorted(
            output,
            key=lambda item: (item.snapshot_ts_ms, item.horizon_min),
        )
    def outcome_status_counts(
        self,
        symbol: str,
        kind: str,
        *,
        as_of_ms: int,
        settlement_grace_ms: int = 300_000,
        experiment_id: str | None = None,
        evidence_role: str | None = None,
    ) -> dict[str, int]:
        """Classify one candidate's outcomes without treating future work as backlog."""
        cutoff = int(as_of_ms) - max(0, int(settlement_grace_ms))
        filters = ""
        params: list[object] = [
            int(as_of_ms), int(as_of_ms), cutoff, cutoff,
            symbol.upper(), kind.upper(), int(as_of_ms),
        ]
        if experiment_id is not None:
            filters += " AND d.experiment_id=?"
            params.append(str(experiment_id))
        if evidence_role is not None:
            role = str(evidence_role).upper()
            if role not in EVIDENCE_ROLES:
                raise ValueError("unsupported prediction evidence role")
            filters += " AND d.evidence_role=?"
            params.append(role)
        with self._connect() as connection:
            row = connection.execute(
                f"""SELECT
                       COUNT(*),
                       SUM(CASE WHEN o.outcome_json IS NOT NULL THEN 1 ELSE 0 END),
                       SUM(CASE WHEN o.expired_at_ms IS NOT NULL THEN 1 ELSE 0 END),
                       SUM(CASE WHEN o.resolved_at_ms IS NULL
                                 AND o.eligible_at_ms>? THEN 1 ELSE 0 END),
                       SUM(CASE WHEN o.resolved_at_ms IS NULL
                                 AND o.eligible_at_ms<=?
                                 AND o.eligible_at_ms>? THEN 1 ELSE 0 END),
                       SUM(CASE WHEN o.resolved_at_ms IS NULL
                                 AND o.eligible_at_ms<=? THEN 1 ELSE 0 END),
                       COUNT(DISTINCT d.snapshot_ts_ms),
                       MIN(d.snapshot_ts_ms),
                       MAX(d.snapshot_ts_ms)
                   FROM prediction_outcomes o
                   JOIN prediction_decisions d ON d.decision_id=o.decision_id
                   WHERE d.symbol=? AND d.kind=?
                     AND d.snapshot_ts_ms<=?{filters}""",
                params,
            ).fetchone()
        values = tuple(int(value or 0) for value in row)
        return dict(zip(
            ("total", "resolved", "expired", "future", "settling", "overdue",
             "cohort_snapshots", "first_snapshot_ts_ms", "last_snapshot_ts_ms"),
            values,
        ))

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
            "regime_performance": self.regime_performance(symbol),
        }
