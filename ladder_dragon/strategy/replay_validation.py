# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compare replay predictions with sanitized real execution outcomes.
"""Empirical replay validation against authoritative execution reports."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Iterable

from ladder_dragon.execution.execution_latency import ExecutionOutcome
from ladder_dragon.strategy.market_replay import (
    MarketEvent,
    OrderBookReplay,
    ReplayCalibration,
    ReplayOrder,
)


TERMINAL_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}


@dataclass(frozen=True)
class ReplayValidation:
    """Summarize prediction errors without exposing exchange identifiers."""

    ready: bool
    reasons: tuple[str, ...]
    archive_sha256: str
    covered_orders: int
    excluded_orders: int
    actual_filled_orders: int
    replay_filled_orders: int
    fill_classification_accuracy: Decimal
    fill_ratio_mae: Decimal
    price_error_bps_mae: Decimal | None
    latency_error_ms_mae: Decimal | None
    fee_error_quote_mae: Decimal | None = None
    slippage_error_bps_mae: Decimal | None = None
    archive_sha256s: tuple[str, ...] = ()
    queue_model: str = "L2_PRICE_LEVEL_FIFO_PROXY"
    exact_l3: bool = False
    actual_limit_maker_filled_orders: int = 0
    actual_stop_limit_filled_orders: int = 0
    maker_buy_fee_pct: Decimal | None = None
    maker_sell_fee_pct: Decimal | None = None
    taker_buy_fee_pct: Decimal | None = None
    taker_sell_fee_pct: Decimal | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 5,
            "ready": self.ready,
            "reasons": list(self.reasons),
            "archive_sha256": self.archive_sha256,
            "archive_sha256s": list(self.archive_sha256s),
            "covered_orders": self.covered_orders,
            "excluded_orders": self.excluded_orders,
            "actual_filled_orders": self.actual_filled_orders,
            "replay_filled_orders": self.replay_filled_orders,
            "fill_classification_accuracy": format(
                self.fill_classification_accuracy, "f"
            ),
            "fill_ratio_mae": format(self.fill_ratio_mae, "f"),
            "price_error_bps_mae": (
                format(self.price_error_bps_mae, "f")
                if self.price_error_bps_mae is not None else None
            ),
            "latency_error_ms_mae": (
                format(self.latency_error_ms_mae, "f")
                if self.latency_error_ms_mae is not None else None
            ),
            "fee_error_quote_mae": (
                format(self.fee_error_quote_mae, "f")
                if self.fee_error_quote_mae is not None else None
            ),
            "slippage_error_bps_mae": (
                format(self.slippage_error_bps_mae, "f")
                if self.slippage_error_bps_mae is not None else None
            ),
            "queue_model": self.queue_model,
            "exact_l3": self.exact_l3,
            "actual_limit_maker_filled_orders": (
                self.actual_limit_maker_filled_orders
            ),
            "actual_stop_limit_filled_orders": (
                self.actual_stop_limit_filled_orders
            ),
            "maker_buy_fee_pct": (
                format(self.maker_buy_fee_pct, "f")
                if self.maker_buy_fee_pct is not None else None
            ),
            "maker_sell_fee_pct": (
                format(self.maker_sell_fee_pct, "f")
                if self.maker_sell_fee_pct is not None else None
            ),
            "taker_buy_fee_pct": (
                format(self.taker_buy_fee_pct, "f")
                if self.taker_buy_fee_pct is not None else None
            ),
            "taker_sell_fee_pct": (
                format(self.taker_sell_fee_pct, "f")
                if self.taker_sell_fee_pct is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ReplayValidation":
        schema = int(payload.get("schema_version", 0))
        if schema not in {1, 2, 3, 4, 5}:
            raise ValueError("unsupported replay validation schema")

        def optional_decimal(name: str) -> Decimal | None:
            value = payload.get(name)
            return None if value is None else Decimal(str(value))

        return cls(
            ready=bool(payload.get("ready")),
            reasons=tuple(str(item) for item in payload.get("reasons", [])),
            archive_sha256=str(payload.get("archive_sha256", "")),
            archive_sha256s=tuple(
                str(item) for item in payload.get("archive_sha256s", [])
            ),
            covered_orders=int(payload.get("covered_orders", 0)),
            excluded_orders=int(payload.get("excluded_orders", 0)),
            actual_filled_orders=int(payload.get("actual_filled_orders", 0)),
            replay_filled_orders=int(payload.get("replay_filled_orders", 0)),
            fill_classification_accuracy=Decimal(str(
                payload.get("fill_classification_accuracy", "0")
            )),
            fill_ratio_mae=Decimal(str(payload.get("fill_ratio_mae", "0"))),
            price_error_bps_mae=optional_decimal("price_error_bps_mae"),
            latency_error_ms_mae=optional_decimal("latency_error_ms_mae"),
            fee_error_quote_mae=optional_decimal("fee_error_quote_mae"),
            slippage_error_bps_mae=optional_decimal(
                "slippage_error_bps_mae"
            ),
            queue_model=str(
                payload.get("queue_model", "L2_PRICE_LEVEL_FIFO_PROXY")
            ),
            exact_l3=bool(payload.get("exact_l3", False)),
            actual_limit_maker_filled_orders=int(
                payload.get("actual_limit_maker_filled_orders", 0)
            ),
            actual_stop_limit_filled_orders=int(
                payload.get("actual_stop_limit_filled_orders", 0)
            ),
            maker_buy_fee_pct=optional_decimal("maker_buy_fee_pct"),
            maker_sell_fee_pct=optional_decimal("maker_sell_fee_pct"),
            taker_buy_fee_pct=optional_decimal("taker_buy_fee_pct"),
            taker_sell_fee_pct=optional_decimal("taker_sell_fee_pct"),
        )


def _mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _queue_ahead(event: MarketEvent, outcome: ExecutionOutcome) -> Decimal:
    opposite = event.asks if outcome.side == "BUY" else event.bids
    if opposite:
        crosses = (
            outcome.order_price >= opposite[0].price
            if outcome.side == "BUY"
            else outcome.order_price <= opposite[0].price
        )
        if crosses:
            return Decimal("0")
    own_side = event.bids if outcome.side == "BUY" else event.asks
    for level in own_side:
        if level.price == outcome.order_price:
            return level.quantity
    return Decimal("0")


def _simulate_order(
    events: list[MarketEvent],
    outcome: ExecutionOutcome,
    calibration: ReplayCalibration,
    *,
    maker_buy_fee_pct: Decimal,
    maker_sell_fee_pct: Decimal,
    taker_buy_fee_pct: Decimal,
    taker_sell_fee_pct: Decimal,
) -> tuple[Decimal, Decimal, Decimal, int | None]:
    relevant = [
        event for event in events
        if outcome.intent_created_at_ms <= event.ts_ms
        <= outcome.final_received_at_ms
    ]
    if not relevant:
        return Decimal("0"), Decimal("0"), Decimal("0"), None
    replay = OrderBookReplay(
        latency_ms=calibration.latency_ms_p95,
        maker_fee_pct=(
            maker_buy_fee_pct if outcome.side == "BUY" else maker_sell_fee_pct
        ),
        taker_fee_pct=(
            taker_buy_fee_pct if outcome.side == "BUY" else taker_sell_fee_pct
        ),
        market_impact_bps=calibration.market_impact_bps,
    )
    order = ReplayOrder(
        order_id=outcome.order_ref,
        side=outcome.side,
        price=outcome.order_price,
        quantity=outcome.original_quantity,
        created_ts=outcome.intent_created_at_ms,
    )
    stop_pending = outcome.order_type == "STOP_LOSS_LIMIT"
    if stop_pending and (outcome.side != "SELL" or outcome.stop_price <= 0):
        return Decimal("0"), Decimal("0"), Decimal("0"), None
    if not stop_pending:
        replay.submit(
            order,
            outcome.intent_created_at_ms,
            queue_ahead=_queue_ahead(relevant[0], outcome),
        )
    quantity = Decimal("0")
    quote = Decimal("0")
    fee_quote = Decimal("0")
    first_fill_ms: int | None = None
    for event in relevant:
        if stop_pending:
            trigger_prices = [price for price, _qty, _side in event.trades]
            if not trigger_prices or min(trigger_prices) > outcome.stop_price:
                continue
            replay.submit(
                order,
                event.ts_ms,
                queue_ahead=_queue_ahead(event, outcome),
            )
            stop_pending = False
        for fill in replay.process(event):
            if fill.order_id != outcome.order_ref:
                continue
            if first_fill_ms is None:
                first_fill_ms = event.ts_ms
            quantity += fill.quantity
            quote += fill.quantity * fill.price
            fee_quote += fill.fee_quote
    return quantity, quote, fee_quote, first_fill_ms


@dataclass(frozen=True)
class ReplayValidationSession:
    """Bind one calibration to one contiguous public market session."""

    events: tuple[MarketEvent, ...]
    calibration: ReplayCalibration


def _validate_fee_rates(fee_rates: tuple[Decimal, ...]) -> None:
    if any(not value.is_finite() or value < 0 for value in fee_rates):
        raise ValueError("replay validation fee rates are invalid")


def _build_validation_report(
    covered: list[
        tuple[ExecutionOutcome, Decimal, Decimal, Decimal, int | None]
    ],
    *,
    excluded: int,
    archive_sha256: str,
    archive_sha256s: tuple[str, ...],
    calibrations_eligible: bool,
    minimum_orders: int,
    minimum_classification_accuracy: Decimal,
    maximum_fill_ratio_mae: Decimal,
    maximum_price_error_bps_mae: Decimal,
    maximum_latency_error_ms_mae: Decimal,
    maximum_fee_error_quote_mae: Decimal,
    maximum_slippage_error_bps_mae: Decimal,
    maker_buy_fee_pct: Decimal,
    maker_sell_fee_pct: Decimal,
    taker_buy_fee_pct: Decimal,
    taker_sell_fee_pct: Decimal,
) -> ReplayValidation:
    """Aggregate simulations after strict session coverage is established."""
    classification_hits = 0
    ratio_errors: list[Decimal] = []
    price_errors: list[Decimal] = []
    latency_errors: list[Decimal] = []
    fee_errors: list[Decimal] = []
    slippage_errors: list[Decimal] = []
    actual_filled = 0
    replay_filled = 0
    actual_limit_maker = 0
    actual_stop_limit = 0
    for (
        outcome,
        replay_quantity,
        replay_quote,
        replay_fee,
        replay_first_fill,
    ) in covered:
        actual_has_fill = outcome.cumulative_quantity > 0
        replay_has_fill = replay_quantity > 0
        actual_filled += int(actual_has_fill)
        replay_filled += int(replay_has_fill)
        actual_limit_maker += int(
            actual_has_fill and outcome.order_type == "LIMIT_MAKER"
        )
        actual_stop_limit += int(
            actual_has_fill and outcome.order_type == "STOP_LOSS_LIMIT"
        )
        classification_hits += int(actual_has_fill == replay_has_fill)
        replay_ratio = min(
            Decimal("1"), replay_quantity / outcome.original_quantity
        )
        ratio_errors.append(abs(outcome.fill_ratio - replay_ratio))
        actual_price = outcome.average_fill_price
        if actual_price is not None and replay_quantity > 0:
            replay_price = replay_quote / replay_quantity
            price_errors.append(
                abs(replay_price / actual_price - Decimal("1"))
                * Decimal("10000")
            )
            actual_slippage = abs(
                actual_price / outcome.order_price - Decimal("1")
            ) * Decimal("10000")
            replay_slippage = abs(
                replay_price / outcome.order_price - Decimal("1")
            ) * Decimal("10000")
            slippage_errors.append(abs(replay_slippage - actual_slippage))
            if outcome.commission_quote is not None:
                fee_errors.append(abs(replay_fee - outcome.commission_quote))
        if (
            outcome.first_fill_received_at_ms is not None
            and replay_first_fill is not None
        ):
            actual_latency = (
                outcome.first_fill_received_at_ms
                - outcome.intent_created_at_ms
            )
            replay_latency = replay_first_fill - outcome.intent_created_at_ms
            latency_errors.append(Decimal(abs(replay_latency - actual_latency)))

    sample_count = len(covered)
    accuracy = (
        Decimal(classification_hits) / Decimal(sample_count)
        if sample_count else Decimal("0")
    )
    ratio_mae = _mean(ratio_errors) or Decimal("0")
    price_mae = _mean(price_errors)
    latency_mae = _mean(latency_errors)
    fee_mae = _mean(fee_errors)
    slippage_mae = _mean(slippage_errors)
    reasons: list[str] = []
    if not calibrations_eligible:
        reasons.append("calibration is not eligible")
    if sample_count < minimum_orders:
        reasons.append(f"covered orders {sample_count} < {minimum_orders}")
    if actual_limit_maker < 1:
        reasons.append("actual LIMIT_MAKER coverage is unavailable")
    if actual_stop_limit < 1:
        reasons.append("actual STOP_LOSS_LIMIT coverage is unavailable")
    if accuracy < minimum_classification_accuracy:
        reasons.append("fill classification accuracy below threshold")
    if ratio_mae > maximum_fill_ratio_mae:
        reasons.append("fill ratio error above threshold")
    if price_mae is None:
        reasons.append("matched fill prices unavailable")
    elif price_mae > maximum_price_error_bps_mae:
        reasons.append("fill price error above threshold")
    if latency_mae is None:
        reasons.append("matched fill latencies unavailable")
    elif latency_mae > maximum_latency_error_ms_mae:
        reasons.append("fill latency error above threshold")
    if fee_mae is None:
        reasons.append("matched exact fees unavailable")
    elif fee_mae > maximum_fee_error_quote_mae:
        reasons.append("fill fee error above threshold")
    if slippage_mae is None:
        reasons.append("matched slippage unavailable")
    elif slippage_mae > maximum_slippage_error_bps_mae:
        reasons.append("fill slippage error above threshold")
    return ReplayValidation(
        ready=not reasons,
        reasons=tuple(reasons),
        archive_sha256=archive_sha256,
        archive_sha256s=archive_sha256s,
        covered_orders=sample_count,
        excluded_orders=excluded,
        actual_filled_orders=actual_filled,
        replay_filled_orders=replay_filled,
        fill_classification_accuracy=accuracy,
        fill_ratio_mae=ratio_mae,
        price_error_bps_mae=price_mae,
        latency_error_ms_mae=latency_mae,
        fee_error_quote_mae=fee_mae,
        slippage_error_bps_mae=slippage_mae,
        actual_limit_maker_filled_orders=actual_limit_maker,
        actual_stop_limit_filled_orders=actual_stop_limit,
        maker_buy_fee_pct=maker_buy_fee_pct,
        maker_sell_fee_pct=maker_sell_fee_pct,
        taker_buy_fee_pct=taker_buy_fee_pct,
        taker_sell_fee_pct=taker_sell_fee_pct,
    )


def validate_replay_outcomes(
    events: Iterable[MarketEvent],
    outcomes: Iterable[ExecutionOutcome],
    calibration: ReplayCalibration,
    *,
    minimum_orders: int = 10,
    minimum_classification_accuracy: Decimal = Decimal("0.80"),
    maximum_fill_ratio_mae: Decimal = Decimal("0.25"),
    maximum_price_error_bps_mae: Decimal = Decimal("10"),
    maximum_latency_error_ms_mae: Decimal = Decimal("1000"),
    maximum_fee_error_quote_mae: Decimal = Decimal("0.02"),
    maximum_slippage_error_bps_mae: Decimal = Decimal("10"),
    maker_buy_fee_pct: Decimal = Decimal("0.00075"),
    maker_sell_fee_pct: Decimal = Decimal("0.00075"),
    taker_buy_fee_pct: Decimal = Decimal("0.001"),
    taker_sell_fee_pct: Decimal = Decimal("0.001"),
) -> ReplayValidation:
    """Replay terminal real orders and fail closed on insufficient accuracy."""
    rows = sorted(events, key=lambda event: event.ts_ms)
    if not rows:
        raise ValueError("replay validation requires market events")
    if minimum_orders < 1:
        raise ValueError("minimum orders must be positive")
    fee_rates = (
        maker_buy_fee_pct,
        maker_sell_fee_pct,
        taker_buy_fee_pct,
        taker_sell_fee_pct,
    )
    _validate_fee_rates(fee_rates)
    covered: list[
        tuple[ExecutionOutcome, Decimal, Decimal, Decimal, int | None]
    ] = []
    excluded = 0
    for outcome in outcomes:
        if (
            outcome.final_status not in TERMINAL_STATUSES
            or outcome.intent_created_at_ms < rows[0].ts_ms
            or outcome.final_received_at_ms > rows[-1].ts_ms
        ):
            excluded += 1
            continue
        quantity, quote, fee_quote, first_fill_ms = _simulate_order(
            rows,
            outcome,
            calibration,
            maker_buy_fee_pct=maker_buy_fee_pct,
            maker_sell_fee_pct=maker_sell_fee_pct,
            taker_buy_fee_pct=taker_buy_fee_pct,
            taker_sell_fee_pct=taker_sell_fee_pct,
        )
        covered.append(
            (outcome, quantity, quote, fee_quote, first_fill_ms)
        )

    return _build_validation_report(
        covered,
        excluded=excluded,
        archive_sha256=calibration.archive_sha256,
        archive_sha256s=(calibration.archive_sha256,),
        calibrations_eligible=calibration.eligible,
        minimum_orders=minimum_orders,
        minimum_classification_accuracy=minimum_classification_accuracy,
        maximum_fill_ratio_mae=maximum_fill_ratio_mae,
        maximum_price_error_bps_mae=maximum_price_error_bps_mae,
        maximum_latency_error_ms_mae=maximum_latency_error_ms_mae,
        maximum_fee_error_quote_mae=maximum_fee_error_quote_mae,
        maximum_slippage_error_bps_mae=maximum_slippage_error_bps_mae,
        maker_buy_fee_pct=maker_buy_fee_pct,
        maker_sell_fee_pct=maker_sell_fee_pct,
        taker_buy_fee_pct=taker_buy_fee_pct,
        taker_sell_fee_pct=taker_sell_fee_pct,
    )


def validate_replay_sessions(
    sessions: Iterable[ReplayValidationSession],
    outcomes: Iterable[ExecutionOutcome],
    **thresholds: object,
) -> ReplayValidation:
    """Validate separate archives without fabricating continuity across gaps."""
    rows = list(sessions)
    if not rows:
        raise ValueError("replay validation requires sessions")
    prepared: list[tuple[list[MarketEvent], ReplayCalibration]] = []
    hashes: list[str] = []
    intervals: list[tuple[int, int]] = []
    for session in rows:
        events = sorted(session.events, key=lambda event: event.ts_ms)
        if not events:
            raise ValueError("replay validation session has no market events")
        calibration = session.calibration
        if (
            events[0].ts_ms != calibration.first_ts_ms
            or events[-1].ts_ms != calibration.last_ts_ms
        ):
            raise ValueError("replay validation session calibration is mismatched")
        digest = calibration.archive_sha256
        if len(digest) != 64 or digest in hashes:
            raise ValueError("replay validation archive identity is invalid")
        hashes.append(digest)
        intervals.append((events[0].ts_ms, events[-1].ts_ms))
        prepared.append((events, calibration))
    ordered_intervals = sorted(intervals)
    if any(
        current[0] <= previous[1]
        for previous, current in zip(ordered_intervals, ordered_intervals[1:])
    ):
        raise ValueError("replay validation sessions overlap")

    defaults: dict[str, object] = {
        "minimum_orders": 10,
        "minimum_classification_accuracy": Decimal("0.80"),
        "maximum_fill_ratio_mae": Decimal("0.25"),
        "maximum_price_error_bps_mae": Decimal("10"),
        "maximum_latency_error_ms_mae": Decimal("1000"),
        "maximum_fee_error_quote_mae": Decimal("0.02"),
        "maximum_slippage_error_bps_mae": Decimal("10"),
        "maker_buy_fee_pct": Decimal("0.00075"),
        "maker_sell_fee_pct": Decimal("0.00075"),
        "taker_buy_fee_pct": Decimal("0.001"),
        "taker_sell_fee_pct": Decimal("0.001"),
    }
    unknown = set(thresholds) - set(defaults)
    if unknown:
        raise TypeError(f"unknown replay validation options: {sorted(unknown)}")
    defaults.update(thresholds)
    minimum_orders = int(defaults["minimum_orders"])
    if minimum_orders < 1:
        raise ValueError("minimum orders must be positive")
    maker_buy = Decimal(str(defaults["maker_buy_fee_pct"]))
    maker_sell = Decimal(str(defaults["maker_sell_fee_pct"]))
    taker_buy = Decimal(str(defaults["taker_buy_fee_pct"]))
    taker_sell = Decimal(str(defaults["taker_sell_fee_pct"]))
    _validate_fee_rates((maker_buy, maker_sell, taker_buy, taker_sell))

    covered: list[
        tuple[ExecutionOutcome, Decimal, Decimal, Decimal, int | None]
    ] = []
    excluded = 0
    for outcome in outcomes:
        matches = [
            item for item in prepared
            if outcome.final_status in TERMINAL_STATUSES
            and outcome.intent_created_at_ms >= item[0][0].ts_ms
            and outcome.final_received_at_ms <= item[0][-1].ts_ms
        ]
        if len(matches) != 1:
            excluded += 1
            continue
        events, calibration = matches[0]
        covered.append(
            (
                outcome,
                *_simulate_order(
                    events,
                    outcome,
                    calibration,
                    maker_buy_fee_pct=maker_buy,
                    maker_sell_fee_pct=maker_sell,
                    taker_buy_fee_pct=taker_buy,
                    taker_sell_fee_pct=taker_sell,
                ),
            )
        )
    ordered_hashes = tuple(
        digest for _interval, digest in sorted(zip(intervals, hashes))
    )
    bundle_sha = hashlib.sha256("\n".join(ordered_hashes).encode()).hexdigest()
    return _build_validation_report(
        covered,
        excluded=excluded,
        archive_sha256=bundle_sha,
        archive_sha256s=ordered_hashes,
        calibrations_eligible=all(item[1].eligible for item in prepared),
        minimum_orders=minimum_orders,
        minimum_classification_accuracy=Decimal(
            str(defaults["minimum_classification_accuracy"])
        ),
        maximum_fill_ratio_mae=Decimal(
            str(defaults["maximum_fill_ratio_mae"])
        ),
        maximum_price_error_bps_mae=Decimal(
            str(defaults["maximum_price_error_bps_mae"])
        ),
        maximum_latency_error_ms_mae=Decimal(
            str(defaults["maximum_latency_error_ms_mae"])
        ),
        maximum_fee_error_quote_mae=Decimal(
            str(defaults["maximum_fee_error_quote_mae"])
        ),
        maximum_slippage_error_bps_mae=Decimal(
            str(defaults["maximum_slippage_error_bps_mae"])
        ),
        maker_buy_fee_pct=maker_buy,
        maker_sell_fee_pct=maker_sell,
        taker_buy_fee_pct=taker_buy,
        taker_sell_fee_pct=taker_sell,
    )


def write_replay_validation(
    path: str | Path, report: ReplayValidation
) -> None:
    Path(path).write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_replay_validation(path: str | Path) -> ReplayValidation:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("replay validation must be a JSON object")
    return ReplayValidation.from_dict(payload)
