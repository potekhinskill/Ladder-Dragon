# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: apply control-specific statistical criteria to SHADOW evidence.

"""Separate approval semantics for expectancy, inventory, maker, and regime."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from ladder_dragon.strategy.prediction.approval import bootstrap_mean_ci
from ladder_dragon.strategy.prediction.confirmation_statistics import drawdown
from ladder_dragon.strategy.prediction.models import ResolvedSample


D = Decimal
ZERO = D("0")
MINIMUM_INDEPENDENT_SNAPSHOTS = 120


def _snapshot_values(
    samples: Sequence[ResolvedSample],
) -> list[dict[str, object]]:
    grouped: dict[int, list[ResolvedSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.snapshot_ts_ms, []).append(sample)
    output = []
    for timestamp, rows in sorted(grouped.items()):
        count = D(str(len(rows)))
        candidate = sum(
            (row.outcome.net_pnl_quote for row in rows), ZERO
        ) / count
        baseline = sum(
            (row.baseline_net_pnl_quote for row in rows), ZERO
        ) / count
        output.append({
            "timestamp": timestamp,
            "regime": rows[0].regime,
            "candidate": candidate,
            "baseline": baseline,
            "edge": candidate - baseline,
        })
    return output


def _lower_quantile(values: Sequence[Decimal], numerator: int = 1) -> Decimal:
    if not values:
        return ZERO
    ordered = sorted(values)
    index = max(0, (len(ordered) * numerator + 9) // 10 - 1)
    return ordered[min(index, len(ordered) - 1)]


def control_specific_gate(
    control: str,
    samples: Sequence[ResolvedSample],
) -> dict[str, object]:
    """Evaluate one control with criteria that match its intended effect."""
    normalized = str(control).strip().lower()
    if normalized == "maker":
        # Zeroing simulated slippage does not prove LIMIT_MAKER execution.
        # Promotion stays blocked until maker fills and missed fills are stored.
        return {
            "approved": False,
            "mode": "SHADOW",
            "policy": "maker_execution_v1",
            "reasons": [
                "maker fills and missed fills are not represented in evidence"
            ],
            "independent_samples": 0,
        }
    rows = _snapshot_values(samples)
    candidate = [row["candidate"] for row in rows]
    baseline = [row["baseline"] for row in rows]
    edges = [row["edge"] for row in rows]
    reasons = []
    if len(rows) < MINIMUM_INDEPENDENT_SNAPSHOTS:
        reasons.append("insufficient independent samples")
    edge_ci = bootstrap_mean_ci(edges)
    candidate_drawdown = drawdown(candidate)
    baseline_drawdown = drawdown(baseline)
    report: dict[str, object] = {
        "approved": False,
        "mode": "SHADOW",
        "policy": f"{normalized}_control_v1",
        "reasons": reasons,
        "independent_samples": len(rows),
        "baseline_edge_ci": [format(edge_ci[0], "f"), format(edge_ci[1], "f")],
        "candidate_drawdown_quote": format(candidate_drawdown, "f"),
        "baseline_drawdown_quote": format(baseline_drawdown, "f"),
    }
    if normalized == "inventory":
        candidate_tail = _lower_quantile(candidate)
        baseline_tail = _lower_quantile(baseline)
        if candidate_tail <= baseline_tail:
            reasons.append("inventory tail loss did not improve")
        if candidate_drawdown >= baseline_drawdown:
            reasons.append("inventory drawdown did not improve")
        report.update({
            "candidate_tail_quote": format(candidate_tail, "f"),
            "baseline_tail_quote": format(baseline_tail, "f"),
            "profit_superiority_required": False,
        })
    elif normalized == "regime":
        if edge_ci[0] <= 0:
            reasons.append("regime baseline edge lower CI is not positive")
        if candidate_drawdown > baseline_drawdown:
            reasons.append("regime drawdown is worse than baseline")
        counts = {
            regime: sum(row["regime"] == regime for row in rows)
            for regime in ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
        }
        if any(value < 20 for value in counts.values()):
            reasons.append("market regime coverage is incomplete")
        report["regime_counts"] = counts
    else:
        raise ValueError("unsupported control-specific policy")
    report["approved"] = not reasons
    report["mode"] = "APPLY" if not reasons else "SHADOW"
    return report


__all__ = ["control_specific_gate"]
