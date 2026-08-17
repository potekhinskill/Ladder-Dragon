# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: apply control-specific statistical criteria to SHADOW evidence.

"""Separate approval semantics for expectancy, inventory, maker, and regime."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
from typing import Sequence

from ladder_dragon.strategy.prediction.approval import (
    binomial_upper_rate,
    bootstrap_mean_ci,
)
from ladder_dragon.strategy.prediction.confirmation_statistics import drawdown
from ladder_dragon.strategy.prediction.models import ResolvedSample


D = Decimal
ZERO = D("0")
MINIMUM_INDEPENDENT_SNAPSHOTS = 120
NONINFERIORITY_MARGIN_BPS = D("5")
MAXIMUM_EVIDENCE_DURATION_MS = 180 * 24 * 60 * 60_000
CONTROL_FIELDS = {
    "expectancy": {"take_profit_price"},
    "inventory": {"entry_enabled", "notional_quote"},
    "regime": {"entry_enabled"},
}


def _validated_metadata(control: str, value: object) -> dict[str, object]:
    """Reject ambiguous control identity before statistical aggregation."""
    if not isinstance(value, dict):
        raise ValueError("control metadata is not an object")
    if value.get("rule") != "v3" or value.get("control") != control:
        raise ValueError("control metadata identity is invalid")
    if type(value.get("binding")) is not bool or type(value.get("applicable")) is not bool:
        raise ValueError("control metadata booleans are invalid")
    if value.get("field") not in CONTROL_FIELDS[control]:
        raise ValueError("control metadata field is invalid")
    before, after = value.get("from"), value.get("to")
    if not isinstance(before, str) or not before or not isinstance(after, str) or not after:
        raise ValueError("control metadata transition is invalid")
    binding = value["binding"]
    if binding != (before != after) or (not value["applicable"] and binding):
        raise ValueError("control metadata binding is inconsistent")
    expected_reason = "plan_changed" if binding else "no_plan_change"
    if value.get("reason") != expected_reason:
        raise ValueError("control metadata reason is inconsistent")
    notional = D(str(value.get("baseline_notional_quote", "")))
    if not notional.is_finite() or notional <= ZERO:
        raise ValueError("control baseline notional must be positive")
    return value


def _binding_reachability(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    """Estimate binding maturity without reading any outcome value."""
    observed = len(rows)
    binding = sum(bool(row["binding"]) for row in rows)
    applicable = sum(bool(row["applicable"]) for row in rows)
    upper = binomial_upper_rate(binding, applicable)
    rate = D(binding) / D(applicable) if applicable else ZERO
    timestamps = [int(row["timestamp"]) for row in rows]
    spacing = max(
        15 * 60_000 + 1,
        min((b - a for a, b in zip(timestamps, timestamps[1:]) if b > a), default=15 * 60_000 + 1),
    )
    estimate_rate = rate if binding else upper
    required_total = (
        int((D(MINIMUM_INDEPENDENT_SNAPSHOTS) / estimate_rate).to_integral_value(rounding=ROUND_CEILING))
        if estimate_rate > ZERO else None
    )
    projected_ready = (
        timestamps[-1] + max(0, required_total - applicable) * spacing
        if timestamps and required_total is not None else None
    )
    projected_duration = (
        max(0, required_total - 1) * spacing
        if required_total is not None else None
    )
    practical = (
        projected_duration <= MAXIMUM_EVIDENCE_DURATION_MS
        if projected_duration is not None else None
    )
    status = "OBSERVING"
    if applicable == 0 and observed:
        status = "NOT_APPLICABLE"
    elif binding >= MINIMUM_INDEPENDENT_SNAPSHOTS:
        status = "READY"
    elif practical is False:
        status = "IMPRACTICAL"
    return {
        "status": status,
        "observed_independent_samples": observed,
        "applicable_independent_samples": applicable,
        "binding_independent_samples": binding,
        "required_binding_independent_samples": MINIMUM_INDEPENDENT_SNAPSHOTS,
        "binding_rate": format(rate, "f") if applicable else None,
        "binding_rate_upper_95": format(upper, "f") if applicable else None,
        "projected_required_independent_samples": required_total,
        "projected_ready_ts_ms": projected_ready,
        "projected_duration_ms": projected_duration,
        "maximum_duration_ms": MAXIMUM_EVIDENCE_DURATION_MS,
        "practically_reachable": practical,
        "outcome_values_used": False,
    }


def _snapshot_values(
    control: str,
    samples: Sequence[ResolvedSample],
    *,
    include_financial: bool = True,
) -> list[dict[str, object]]:
    grouped: dict[int, list[ResolvedSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.snapshot_ts_ms, []).append(sample)
    output = []
    for timestamp, rows in sorted(grouped.items()):
        metadata_rows = [
            _validated_metadata(control, row.decision_metadata)
            for row in rows
        ]
        if any(metadata != metadata_rows[0] for metadata in metadata_rows[1:]):
            raise ValueError("control metadata differs across outcome horizons")
        count = D(str(len(rows)))
        candidate = (
            sum((row.outcome.net_pnl_quote for row in rows), ZERO) / count
            if include_financial else ZERO
        )
        baseline = (
            sum((row.baseline_net_pnl_quote for row in rows), ZERO) / count
            if include_financial else ZERO
        )
        metadata = metadata_rows[0]
        baseline_notional = D(str(metadata.get("baseline_notional_quote", "0")))
        output.append({
            "timestamp": timestamp,
            "regime": rows[0].regime,
            "candidate": candidate,
            "baseline": baseline,
            "edge": candidate - baseline,
            "binding": bool(metadata.get("binding")),
            "applicable": bool(metadata.get("applicable")),
            "baseline_notional": baseline_notional,
            "edge_bps": (
                (candidate - baseline) / baseline_notional * D("10000")
                if baseline_notional > 0 else ZERO
            ),
        })
    return output


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
    rows = _snapshot_values(
        normalized, samples, include_financial=normalized != "inventory"
    )
    if len({row["applicable"] for row in rows}) > 1:
        raise ValueError("control applicability changed inside one evidence version")
    reachability = _binding_reachability(rows)
    if normalized == "inventory":
        status = (
            "NOT_APPLICABLE"
            if reachability["status"] == "NOT_APPLICABLE"
            else "STATEFUL_MODEL_REQUIRED"
        )
        reason = (
            "inventory control does not apply to this observation-only symbol"
            if status == "NOT_APPLICABLE"
            else "inventory promotion requires a sequential portfolio replay"
        )
        return {
            "approved": False,
            "mode": status,
            "status": status,
            "policy": "inventory_control_v2",
            "reasons": [reason],
            "independent_samples": len(rows),
            "binding_independent_samples": sum(bool(row["binding"]) for row in rows),
            "binding_reachability": reachability,
        }
    binding_rows = [row for row in rows if row["binding"]]
    candidate = [row["candidate"] for row in rows]
    baseline = [row["baseline"] for row in rows]
    binding_candidate = [row["candidate"] for row in binding_rows]
    binding_edges = [row["edge"] for row in binding_rows]
    full_edge_bps = [row["edge_bps"] for row in rows]
    reasons = []
    if len(rows) < MINIMUM_INDEPENDENT_SNAPSHOTS:
        reasons.append("insufficient independent samples")
    if len(binding_rows) < MINIMUM_INDEPENDENT_SNAPSHOTS:
        reasons.append("insufficient binding independent samples")
    if reachability["practically_reachable"] is False:
        reasons.append("binding cohort exceeds maximum evidence duration")
    edge_ci = bootstrap_mean_ci(binding_edges)
    full_edge_bps_ci = bootstrap_mean_ci(full_edge_bps)
    candidate_drawdown = drawdown(candidate)
    baseline_drawdown = drawdown(baseline)
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
        "binding_reachability": reachability,
        "binding_edge_ci": [format(edge_ci[0], "f"), format(edge_ci[1], "f")],
        "full_edge_bps_ci": [
            format(full_edge_bps_ci[0], "f"), format(full_edge_bps_ci[1], "f")
        ],
        "noninferiority_margin_bps": format(NONINFERIORITY_MARGIN_BPS, "f"),
        "candidate_drawdown_quote": format(candidate_drawdown, "f"),
        "baseline_drawdown_quote": format(baseline_drawdown, "f"),
    }
    if normalized in {"expectancy", "regime"}:
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
