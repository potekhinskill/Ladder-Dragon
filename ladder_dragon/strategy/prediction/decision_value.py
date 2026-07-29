# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: measure defensive classifier decisions in exact quote-currency value.

"""Money-weighted evaluation for defensive prediction gates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


D = Decimal
ZERO = D("0")
LABELS = ("DOWN", "FLAT", "UP")


@dataclass(frozen=True)
class DecisionValueObservation:
    """One chronologically resolved gate decision.

    ``always_trade_net_pnl_quote`` is the counterfactual result of the unchanged
    baseline trade. A defensive block holds USDT and therefore realizes zero.
    """

    snapshot_ts_ms: int
    resolved_at_ms: int
    predicted_label: str
    realized_return: Decimal
    always_trade_net_pnl_quote: Decimal
    buy_allowed: bool

    def __post_init__(self) -> None:
        if self.resolved_at_ms <= self.snapshot_ts_ms:
            raise ValueError("decision outcome must be resolved after its snapshot")
        if self.predicted_label not in LABELS:
            raise ValueError("predicted_label must be DOWN, FLAT or UP")
        if not (
            self.realized_return.is_finite()
            and self.always_trade_net_pnl_quote.is_finite()
        ):
            raise ValueError("decision-value inputs must be finite")


def direction_label(value: Decimal, *, flat_threshold: Decimal) -> str:
    """Map a realized return to a direction without using future information."""
    if flat_threshold < 0:
        raise ValueError("flat_threshold must be non-negative")
    if value > flat_threshold:
        return "UP"
    if value < -flat_threshold:
        return "DOWN"
    return "FLAT"


def classifier_decision_value_report(
    observations: Iterable[DecisionValueObservation],
    *,
    flat_threshold: Decimal = D("0.001"),
    large_move_threshold: Decimal = D("0.01"),
) -> dict[str, object]:
    """Compare the gate with always trading and weight errors by move size."""
    if large_move_threshold <= flat_threshold:
        raise ValueError("large_move_threshold must exceed flat_threshold")
    rows = sorted(
        observations,
        key=lambda item: (item.snapshot_ts_ms, item.resolved_at_ms),
    )
    confusion = {
        actual: {predicted: 0 for predicted in LABELS}
        for actual in LABELS
    }
    weighted = {
        actual: {predicted: ZERO for predicted in LABELS}
        for actual in LABELS
    }
    large_down_total = 0
    large_down_caught = 0
    always_trade = ZERO
    gated = ZERO
    for row in rows:
        actual = direction_label(
            row.realized_return,
            flat_threshold=flat_threshold,
        )
        magnitude = abs(row.realized_return)
        confusion[actual][row.predicted_label] += 1
        weighted[actual][row.predicted_label] += magnitude
        always_trade += row.always_trade_net_pnl_quote
        if row.buy_allowed:
            gated += row.always_trade_net_pnl_quote
        if (
            actual == "DOWN"
            and magnitude >= large_move_threshold
        ):
            large_down_total += 1
            if not row.buy_allowed:
                large_down_caught += 1
    value = gated - always_trade
    return {
        "schema_version": 1,
        "metric": "defensive-gate-net-value-vs-always-trade",
        "samples": len(rows),
        "always_trade_net_pnl_quote": format(always_trade, "f"),
        "gated_net_pnl_quote": format(gated, "f"),
        "decision_value_quote": format(value, "f"),
        "confusion": confusion,
        "movement_weighted_confusion": {
            actual: {
                predicted: format(value, "f")
                for predicted, value in predictions.items()
            }
            for actual, predictions in weighted.items()
        },
        "large_down_capture": {
            "caught": large_down_caught,
            "total": large_down_total,
            "rate": (
                format(
                    D(str(large_down_caught)) / D(str(large_down_total)),
                    "f",
                )
                if large_down_total else None
            ),
        },
    }
