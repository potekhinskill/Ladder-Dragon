# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: evaluate frozen SHADOW confirmation evidence by independent blocks.
"""Block-native statistics for independent SHADOW confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from ladder_dragon.strategy.prediction.approval import (
    bootstrap_mean_ci,
    holm_configuration_correction,
    paired_sign_p_value,
)
from ladder_dragon.strategy.prediction.models import ResolvedSample
from ladder_dragon.strategy.prediction.statistical_units import (
    non_overlapping_timestamps,
    outcome_spacing_ms,
)
from ladder_dragon.strategy.prediction.statistical_design import (
    DEFAULT_STATISTICAL_DESIGN,
    EXPECTANCY_REGIMES,
    PANIC_REGIME,
    REQUIRED_EVALUATION_SNAPSHOTS,
)


D = Decimal
ZERO = D("0")
DEFAULT_CONFIRMATION_CRITERIA = {
    "min_independent_samples": REQUIRED_EVALUATION_SNAPSHOTS,
    "min_regime_samples": 8,
    "min_fill_rate": "0.10",
    "max_drawdown_quote": "25",
    "window_method": "fixed_non_overlapping_decision_blocks",
    "window_size_decisions": 8,
    "required_complete_windows": 7,
    "minimum_positive_windows": 6,
    "maximum_consecutive_negative_windows": 1,
    "embargo_ms": 900_000,
    "maximum_confirmation_duration_ms": (
        DEFAULT_STATISTICAL_DESIGN.maximum_confirmation_duration_ms
    ),
    "sign_test_power": DEFAULT_STATISTICAL_DESIGN.as_dict(),
}


def minimum_sign_blocks(hypothesis_count: int, *, alpha: float = 0.05) -> int:
    """Return the minimum all-positive block count for the first Holm test."""
    count = int(hypothesis_count)
    if count <= 0 or not 0 < alpha <= 1:
        raise ValueError("Holm feasibility inputs are invalid")
    observations = 1
    while 2 ** (-observations) > alpha / count:
        observations += 1
    return observations


def validate_confirmation_criteria(
    criteria: Mapping[str, object], *, required_horizons_min: Sequence[int]
) -> dict[str, int]:
    """Reject a confirmation design that cannot satisfy its own tests."""
    # Validate capacity before evidence collection. An impossible manifest
    # must fail before it can consume an immutable confirmation cohort.
    spacing = outcome_spacing_ms(required_horizons_min)
    size = int(criteria["window_size_decisions"])
    windows = int(criteria["required_complete_windows"])
    minimum_samples = int(criteria["min_independent_samples"])
    minimum_regime = int(criteria["min_regime_samples"])
    minimum_positive = int(criteria["minimum_positive_windows"])
    maximum_negative = int(criteria["maximum_consecutive_negative_windows"])
    embargo_ms = int(criteria["embargo_ms"])
    if size <= 0 or windows <= 0:
        raise ValueError("confirmation windows must be positive")
    if minimum_samples <= 0 or minimum_regime <= 0:
        raise ValueError("confirmation sample requirements must be positive")
    if size * windows < minimum_samples:
        raise ValueError("confirmation windows cannot reach the sample requirement")
    if minimum_regime * len(EXPECTANCY_REGIMES) > size * windows:
        raise ValueError("regime requirement exceeds confirmation capacity")
    if not 0 <= minimum_positive <= windows:
        raise ValueError("positive-window requirement is impossible")
    if not 0 <= maximum_negative <= windows:
        raise ValueError("negative-window requirement is impossible")
    if embargo_ms < 0:
        raise ValueError("confirmation embargo must be non-negative")
    hypotheses = len(tuple(required_horizons_min)) + len(EXPECTANCY_REGIMES)
    required_sign_blocks = minimum_sign_blocks(hypotheses)
    if windows < required_sign_blocks:
        raise ValueError("confirmation has too few blocks for Holm significance")
    return {
        "independence_spacing_ms": spacing,
        "minimum_sign_blocks": required_sign_blocks,
        "hypothesis_count": hypotheses,
        "minimum_calendar_duration_ms": (
            max(0, minimum_samples - 1) * spacing
            + max(int(value) for value in required_horizons_min) * 60_000
            + embargo_ms
        ),
    }


def non_overlapping_decisions(
    decisions: Sequence[DecisionEvidence], *, required_horizons_min: Sequence[int]
) -> list[DecisionEvidence]:
    """Select decisions whose maximum outcome intervals do not overlap."""
    # Purge outcome overlap before block construction. Later grouping cannot
    # make dependent decisions statistically independent.
    selected = set(non_overlapping_timestamps(
        (item.snapshot_ts_ms for item in decisions),
        horizons_min=required_horizons_min,
    ))
    return [
        item for item in sorted(decisions, key=lambda row: row.snapshot_ts_ms)
        if item.snapshot_ts_ms in selected
    ]


@dataclass(frozen=True)
class DecisionEvidence:
    decision_id: str
    snapshot_ts_ms: int
    regime: str
    samples: tuple[ResolvedSample, ...]
    complete: bool


def drawdown(values: Sequence[Decimal]) -> Decimal:
    cumulative = ZERO
    peak = ZERO
    maximum = ZERO
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum


def summarize_window(
    rows: Sequence[DecisionEvidence], index: int
) -> dict[str, object]:
    pnl: list[Decimal] = []
    baseline: list[Decimal] = []
    fills = ZERO
    no_trade = 0
    opportunity = ZERO
    regimes: dict[str, dict[str, object]] = {}
    for decision in rows:
        count = D(str(len(decision.samples)))
        candidate_value = sum(
            (row.outcome.net_pnl_quote for row in decision.samples), ZERO
        ) / count
        baseline_value = sum(
            (row.baseline_net_pnl_quote for row in decision.samples), ZERO
        ) / count
        fill = sum(
            (D(str(int(row.outcome.buy_filled))) for row in decision.samples), ZERO
        ) / count
        pnl.append(candidate_value)
        baseline.append(baseline_value)
        fills += fill
        if all(row.outcome.exit_reason == "NO_TRADE" for row in decision.samples):
            no_trade += 1
            opportunity += baseline_value
        bucket = regimes.setdefault(
            decision.regime, {"decisions": 0, "pnl": ZERO, "edge": ZERO}
        )
        bucket["decisions"] = int(bucket["decisions"]) + 1
        bucket["pnl"] = bucket["pnl"] + candidate_value
        bucket["edge"] = bucket["edge"] + candidate_value - baseline_value
    candidate_total = sum(pnl, ZERO)
    baseline_total = sum(baseline, ZERO)
    edge = candidate_total - baseline_total
    return {
        "index": index,
        "status": "COMPLETE",
        "start_ts_ms": rows[0].snapshot_ts_ms,
        "end_ts_ms": rows[-1].snapshot_ts_ms,
        "independent_decisions": len(rows),
        "candidate_net_pnl_quote": format(candidate_total, "f"),
        "baseline_net_pnl_quote": format(baseline_total, "f"),
        "edge_quote": format(edge, "f"),
        "fill_rate": format(fills / D(str(len(rows))), "f"),
        "max_drawdown_quote": format(drawdown(pnl), "f"),
        "no_trade_count": no_trade,
        "no_trade_opportunity_cost_quote": format(opportunity, "f"),
        "regimes": {
            name: {
                "decisions": int(value["decisions"]),
                "pnl_quote": format(value["pnl"], "f"),
                "edge_quote": format(value["edge"], "f"),
            }
            for name, value in sorted(regimes.items())
        },
        "absolute_positive": candidate_total > 0,
        "edge_positive": edge > 0,
        "evidence_complete": True,
        "blocking_reasons": [],
        "positive": candidate_total > 0 and edge > 0,
    }


def block_confirmation_gate(
    blocks: Sequence[Sequence[DecisionEvidence]],
    *,
    criteria: Mapping[str, object],
    required_horizons_min: Sequence[int],
) -> dict[str, object]:
    """Evaluate inference on predeclared non-overlapping decision blocks."""
    feasibility = validate_confirmation_criteria(
        criteria, required_horizons_min=required_horizons_min
    )
    decisions = [decision for block in blocks for decision in block]
    pnl: list[Decimal] = []
    edges: list[Decimal] = []
    fills: list[Decimal] = []
    for decision in decisions:
        count = D(str(len(decision.samples)))
        pnl.append(sum(
            (sample.outcome.net_pnl_quote for sample in decision.samples), ZERO
        ) / count)
        edges.append(sum(
            (
                sample.outcome.net_pnl_quote - sample.baseline_net_pnl_quote
                for sample in decision.samples
            ),
            ZERO,
        ) / count)
        fills.append(sum(
            (D(str(int(sample.outcome.buy_filled))) for sample in decision.samples),
            ZERO,
        ) / count)
    block_pnl: list[Decimal] = []
    block_edges: list[Decimal] = []
    offset = 0
    for block in blocks:
        block_pnl.append(sum(pnl[offset:offset + len(block)], ZERO))
        block_edges.append(sum(edges[offset:offset + len(block)], ZERO))
        offset += len(block)
    hypotheses: dict[str, list[Decimal]] = {}
    for horizon in required_horizons_min:
        values = []
        for block in blocks:
            block_values = [
                sample.outcome.net_pnl_quote - sample.baseline_net_pnl_quote
                for decision in block
                for sample in decision.samples
                if sample.horizon_min == int(horizon)
            ]
            if block_values:
                values.append(sum(block_values, ZERO) / D(str(len(block_values))))
        hypotheses[f"horizon_{int(horizon)}"] = values
    required_regimes = EXPECTANCY_REGIMES
    for regime in required_regimes:
        values = []
        for block in blocks:
            block_values = []
            for decision in block:
                if decision.regime != regime:
                    continue
                count = D(str(len(decision.samples)))
                block_values.append(sum(
                    (
                        sample.outcome.net_pnl_quote
                        - sample.baseline_net_pnl_quote
                        for sample in decision.samples
                    ),
                    ZERO,
                ) / count)
            if block_values:
                values.append(sum(block_values, ZERO) / D(str(len(block_values))))
        hypotheses[f"regime_{regime}"] = values
    p_values = {
        name: paired_sign_p_value(values) for name, values in hypotheses.items()
    }
    holm = holm_configuration_correction(p_values)
    net_ci = bootstrap_mean_ci(block_pnl, seed=41)
    edge_ci = bootstrap_mean_ci(block_edges, seed=43)
    fill_rate = sum(fills, ZERO) / D(str(len(fills))) if fills else ZERO
    regime_counts = {
        regime: sum(decision.regime == regime for decision in decisions)
        for regime in required_regimes
    }
    reasons = []
    if len(decisions) < int(criteria["min_independent_samples"]):
        reasons.append("insufficient independent samples")
    if net_ci[0] <= 0:
        reasons.append("window-block net expectancy lower CI is not positive")
    if edge_ci[0] <= 0:
        reasons.append("window-block baseline edge lower CI is not positive")
    if any(
        count < int(criteria["min_regime_samples"])
        for count in regime_counts.values()
    ):
        reasons.append("market regime coverage is incomplete")
    if hypotheses and not all(holm.values()):
        reasons.append("Holm-corrected block hypotheses did not all pass")
    insufficient_hypothesis_blocks = sorted(
        name for name, values in hypotheses.items()
        if len(values) < feasibility["minimum_sign_blocks"]
    )
    if insufficient_hypothesis_blocks:
        reasons.append(
            "hypotheses have too few independent blocks: "
            + ",".join(insufficient_hypothesis_blocks)
        )
    if fill_rate < D(str(criteria["min_fill_rate"])):
        reasons.append("fill rate is below threshold")
    maximum_drawdown = drawdown(pnl)
    if maximum_drawdown > D(str(criteria["max_drawdown_quote"])):
        reasons.append("drawdown exceeds threshold")
    return {
        "approved": not reasons,
        "mode": "SHADOW",
        "apply_allowed": False,
        "method": "fixed-non-overlapping-window-blocks",
        "reasons": reasons,
        "independent_samples": len(decisions),
        "independent_blocks": len(blocks),
        "independence_spacing_ms": feasibility["independence_spacing_ms"],
        "minimum_sign_blocks": feasibility["minimum_sign_blocks"],
        "net_expectancy_ci": [format(net_ci[0], "f"), format(net_ci[1], "f")],
        "baseline_edge_ci": [format(edge_ci[0], "f"), format(edge_ci[1], "f")],
        "fill_rate": format(fill_rate, "f"),
        "max_drawdown_quote": format(maximum_drawdown, "f"),
        "regime_counts": regime_counts,
        "hypotheses": {
            name: {
                "blocks": len(values),
                "p_value": p_values[name],
                "passed": holm[name],
            }
            for name, values in hypotheses.items()
        },
        "panic_safety": {
            "status": "POLICY_REQUIRED",
            "policy": "block_new_entries",
            "observed_independent_samples": sum(
                decision.regime == PANIC_REGIME for decision in decisions
            ),
            "expectancy_hypothesis": False,
            "blocks_expectancy": False,
        },
        "sign_test_power": DEFAULT_STATISTICAL_DESIGN.as_dict(),
    }


__all__ = [
    "DecisionEvidence",
    "block_confirmation_gate",
    "drawdown",
    "minimum_sign_blocks",
    "non_overlapping_decisions",
    "summarize_window",
    "validate_confirmation_criteria",
]
