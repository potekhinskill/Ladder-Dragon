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
NONINFERIORITY_MARGIN_BPS = D("5")


def _snapshot_values(
    samples: Sequence[ResolvedSample],
) -> list[dict[str, object]]:
    grouped: dict[int, list[ResolvedSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.snapshot_ts_ms, []).append(sample)
    output = []
    for timestamp, rows in sorted(grouped.items()):
        metadata_rows = [row.decision_metadata or {} for row in rows]
        if any(metadata != metadata_rows[0] for metadata in metadata_rows[1:]):
            raise ValueError("control metadata differs across outcome horizons")
        count = D(str(len(rows)))
        candidate = sum(
            (row.outcome.net_pnl_quote for row in rows), ZERO
        ) / count
        baseline = sum(
            (row.baseline_net_pnl_quote for row in rows), ZERO
        ) / count
        metadata = metadata_rows[0]
        baseline_notional = D(str(metadata.get("baseline_notional_quote", "0")))
        output.append({
            "timestamp": timestamp,
            "regime": rows[0].regime,
            "candidate": candidate,
            "baseline": baseline,
            "edge": candidate - baseline,
            "binding": bool(metadata.get("binding")),
            "baseline_notional": baseline_notional,
            "edge_bps": (
                (candidate - baseline) / baseline_notional * D("10000")
                if baseline_notional > 0 else ZERO
            ),
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
            "mode": "NOT_IMPLEMENTED",
            "status": "NOT_IMPLEMENTED",
            "policy": "maker_execution_v1",
            "reasons": [
                "maker fills and missed fills are not represented in evidence"
            ],
            "independent_samples": 0,
        }
    rows = _snapshot_values(samples)
    binding_rows = [row for row in rows if row["binding"]]
    candidate = [row["candidate"] for row in rows]
    baseline = [row["baseline"] for row in rows]
    binding_candidate = [row["candidate"] for row in binding_rows]
    binding_baseline = [row["baseline"] for row in binding_rows]
    binding_edges = [row["edge"] for row in binding_rows]
    full_edge_bps = [row["edge_bps"] for row in rows]
    reasons = []
    if len(rows) < MINIMUM_INDEPENDENT_SNAPSHOTS:
        reasons.append("insufficient independent samples")
    if len(binding_rows) < MINIMUM_INDEPENDENT_SNAPSHOTS:
        reasons.append("insufficient binding independent samples")
    edge_ci = bootstrap_mean_ci(binding_edges)
    full_edge_bps_ci = bootstrap_mean_ci(full_edge_bps)
    candidate_drawdown = drawdown(candidate)
    baseline_drawdown = drawdown(baseline)
    binding_candidate_drawdown = drawdown(binding_candidate)
    binding_baseline_drawdown = drawdown(binding_baseline)
    if full_edge_bps_ci[0] < -NONINFERIORITY_MARGIN_BPS:
        reasons.append("full cohort exceeds the non-inferiority margin")
    if candidate_drawdown > baseline_drawdown:
        reasons.append("full cohort drawdown is worse than baseline")
    report: dict[str, object] = {
        "approved": False,
        "mode": "SHADOW",
        "policy": f"{normalized}_control_v1",
        "reasons": reasons,
        "independent_samples": len(rows),
        "binding_independent_samples": len(binding_rows),
        "binding_edge_ci": [format(edge_ci[0], "f"), format(edge_ci[1], "f")],
        "full_edge_bps_ci": [
            format(full_edge_bps_ci[0], "f"), format(full_edge_bps_ci[1], "f")
        ],
        "noninferiority_margin_bps": format(NONINFERIORITY_MARGIN_BPS, "f"),
        "candidate_drawdown_quote": format(candidate_drawdown, "f"),
        "baseline_drawdown_quote": format(baseline_drawdown, "f"),
    }
    if normalized == "inventory":
        candidate_tail = _lower_quantile(binding_candidate)
        baseline_tail = _lower_quantile(binding_baseline)
        if candidate_tail <= baseline_tail:
            reasons.append("inventory tail loss did not improve")
        if binding_candidate_drawdown >= binding_baseline_drawdown:
            reasons.append("inventory drawdown did not improve")
        report.update({
            "candidate_tail_quote": format(candidate_tail, "f"),
            "baseline_tail_quote": format(baseline_tail, "f"),
            "profit_superiority_required": False,
        })
    elif normalized in {"expectancy", "regime"}:
        if edge_ci[0] <= 0:
            reasons.append(f"{normalized} binding edge lower CI is not positive")
        if normalized == "expectancy":
            candidate_ci = bootstrap_mean_ci(binding_candidate)
            if candidate_ci[0] <= 0:
                reasons.append("expectancy binding net lower CI is not positive")
            report["binding_net_expectancy_ci"] = [
                format(candidate_ci[0], "f"), format(candidate_ci[1], "f")
            ]
        else:
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
