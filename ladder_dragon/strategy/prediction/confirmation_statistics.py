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


D = Decimal
ZERO = D("0")


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
    required_regimes = ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
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
    }


__all__ = [
    "DecisionEvidence",
    "block_confirmation_gate",
    "drawdown",
    "summarize_window",
]
