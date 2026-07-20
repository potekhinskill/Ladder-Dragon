# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compare replay predictions with sanitized real execution outcomes.
"""Empirical replay validation against authoritative execution reports."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
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

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ready": self.ready,
            "reasons": list(self.reasons),
            "archive_sha256": self.archive_sha256,
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
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ReplayValidation":
        if int(payload.get("schema_version", 0)) != 1:
            raise ValueError("unsupported replay validation schema")

        def optional_decimal(name: str) -> Decimal | None:
            value = payload.get(name)
            return None if value is None else Decimal(str(value))

        return cls(
            ready=bool(payload.get("ready")),
            reasons=tuple(str(item) for item in payload.get("reasons", [])),
            archive_sha256=str(payload.get("archive_sha256", "")),
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
) -> tuple[Decimal, Decimal, int | None]:
    relevant = [
        event for event in events
        if outcome.intent_created_at_ms <= event.ts_ms
        <= outcome.final_received_at_ms
    ]
    if not relevant:
        return Decimal("0"), Decimal("0"), None
    replay = OrderBookReplay(
        latency_ms=calibration.latency_ms_p95,
        market_impact_bps=calibration.market_impact_bps,
    )
    order = ReplayOrder(
        order_id=outcome.order_ref,
        side=outcome.side,
        price=outcome.order_price,
        quantity=outcome.original_quantity,
        created_ts=outcome.intent_created_at_ms,
    )
    replay.submit(
        order,
        outcome.intent_created_at_ms,
        queue_ahead=_queue_ahead(relevant[0], outcome),
    )
    quantity = Decimal("0")
    quote = Decimal("0")
    first_fill_ms: int | None = None
    for event in relevant:
        for order_ref, fill_quantity, fill_price in replay.process(event):
            if order_ref != outcome.order_ref:
                continue
            if first_fill_ms is None:
                first_fill_ms = event.ts_ms
            quantity += fill_quantity
            quote += fill_quantity * fill_price
    return quantity, quote, first_fill_ms


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
) -> ReplayValidation:
    """Replay terminal real orders and fail closed on insufficient accuracy."""
    rows = sorted(events, key=lambda event: event.ts_ms)
    if not rows:
        raise ValueError("replay validation requires market events")
    if minimum_orders < 1:
        raise ValueError("minimum orders must be positive")
    covered: list[tuple[ExecutionOutcome, Decimal, Decimal, int | None]] = []
    excluded = 0
    for outcome in outcomes:
        if (
            outcome.final_status not in TERMINAL_STATUSES
            or outcome.intent_created_at_ms < rows[0].ts_ms
            or outcome.final_received_at_ms > rows[-1].ts_ms
        ):
            excluded += 1
            continue
        quantity, quote, first_fill_ms = _simulate_order(
            rows, outcome, calibration
        )
        covered.append((outcome, quantity, quote, first_fill_ms))

    classification_hits = 0
    ratio_errors: list[Decimal] = []
    price_errors: list[Decimal] = []
    latency_errors: list[Decimal] = []
    actual_filled = 0
    replay_filled = 0
    for outcome, replay_quantity, replay_quote, replay_first_fill in covered:
        actual_has_fill = outcome.cumulative_quantity > 0
        replay_has_fill = replay_quantity > 0
        actual_filled += int(actual_has_fill)
        replay_filled += int(replay_has_fill)
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
    reasons: list[str] = []
    if not calibration.eligible:
        reasons.append("calibration is not eligible")
    if sample_count < minimum_orders:
        reasons.append(f"covered orders {sample_count} < {minimum_orders}")
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
    return ReplayValidation(
        ready=not reasons,
        reasons=tuple(reasons),
        archive_sha256=calibration.archive_sha256,
        covered_orders=sample_count,
        excluded_orders=excluded,
        actual_filled_orders=actual_filled,
        replay_filled_orders=replay_filled,
        fill_classification_accuracy=accuracy,
        fill_ratio_mae=ratio_mae,
        price_error_bps_mae=price_mae,
        latency_error_ms_mae=latency_mae,
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
