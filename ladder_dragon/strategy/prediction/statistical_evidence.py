# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: stream independent statistical evidence without loading full history.

"""Bounded-memory access to immutable, non-overlapping prediction evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Sequence

from ladder_dragon.strategy.prediction.models import ResolvedSample, decision_metadata
from ladder_dragon.strategy.prediction.statistical_units import outcome_spacing_ms


MAX_INDEPENDENT_SNAPSHOTS = 512


@dataclass(frozen=True)
class IndependentEvidence:
    """A chronological prefix of complete, independent decision snapshots."""

    samples: tuple[ResolvedSample, ...]
    scanned_snapshots: int
    excluded_overlapping_snapshots: int
    stopped_at_pending_snapshot: bool
    total_independent_snapshots: int
    retained_binding_snapshots: int
    discarded_nonbinding_snapshots: int
    cohort_summary: dict[str, object]


def resolved_independent_evidence(
    store: object,
    symbol: str,
    *,
    kind: str,
    required_horizons_min: Sequence[int],
    before_ts_ms: int | None = None,
    resolved_before_ts_ms: int | None = None,
    experiment_id: str | None = None,
    evidence_role: str | None = None,
    maximum_snapshots: int = MAX_INDEPENDENT_SNAPSHOTS,
    prefer_binding: bool = False,
) -> IndependentEvidence:
    """Stream the full cohort and retain only a stable independent prefix."""
    horizons = tuple(int(value) for value in required_horizons_min)
    if not horizons or tuple(sorted(set(horizons))) != horizons:
        raise ValueError("statistical horizons must be unique and increasing")
    if maximum_snapshots <= 0:
        raise ValueError("maximum statistical snapshots must be positive")
    normalized_kind = str(kind).upper()
    query = """SELECT d.decision_id,d.snapshot_ts_ms,d.feature_json,
                      d.algorithm_decision,o.horizon_min,o.outcome_json,
                      o.baseline_outcome_json,o.resolved_at_ms,
                      d.plan_json,d.baseline_plan_json
               FROM prediction_decisions d
               LEFT JOIN prediction_outcomes o ON o.decision_id=d.decision_id
               WHERE d.symbol=? AND d.kind=?"""
    params: list[object] = [symbol.upper(), normalized_kind]
    if experiment_id is not None:
        query += " AND d.experiment_id=?"
        params.append(str(experiment_id))
    if evidence_role is not None:
        role = str(evidence_role).upper()
        if role not in {"SELECTION", "CONFIRMATION", "DIAGNOSTIC", "LEGACY"}:
            raise ValueError("unsupported prediction evidence role")
        query += " AND d.evidence_role=?"
        params.append(role)
    if before_ts_ms is not None:
        query += " AND d.snapshot_ts_ms<=?"
        params.append(int(before_ts_ms))
    # rowid is the append-only journal order. Streaming it avoids an unbounded
    # result list or a large SQLite temporary sort on the Raspberry Pi.
    query += " ORDER BY d.rowid,o.horizon_min"

    output: list[ResolvedSample] = []
    scanned = 0
    excluded = 0
    stopped_pending = False
    next_allowed_ms: int | None = None
    previous_snapshot: int | None = None
    current: list[tuple[object, ...]] = []
    binding_groups: list[list[ResolvedSample]] = []
    nonbinding_groups: list[list[ResolvedSample]] = []
    total_independent = 0
    total_binding = 0
    discarded_nonbinding = 0
    candidate_total = Decimal("0")
    baseline_total = Decimal("0")
    edge_bps_total = Decimal("0")
    candidate_equity = Decimal("0")
    baseline_equity = Decimal("0")
    candidate_peak = Decimal("0")
    baseline_peak = Decimal("0")
    candidate_max_drawdown = Decimal("0")
    baseline_max_drawdown = Decimal("0")

    def consume(rows: list[tuple[object, ...]]) -> bool:
        nonlocal scanned, excluded, stopped_pending, next_allowed_ms
        nonlocal total_independent, total_binding, discarded_nonbinding
        nonlocal candidate_total, baseline_total, edge_bps_total
        nonlocal candidate_equity, baseline_equity
        nonlocal candidate_peak, baseline_peak
        nonlocal candidate_max_drawdown, baseline_max_drawdown
        if not rows:
            return False
        snapshot = int(rows[0][1])
        scanned += 1
        if next_allowed_ms is not None and snapshot < next_allowed_ms:
            excluded += 1
            return False
        next_allowed_ms = snapshot + outcome_spacing_ms(horizons)
        by_horizon = {int(row[4]): row for row in rows}
        if tuple(sorted(by_horizon)) != horizons:
            stopped_pending = True
            return True
        if any(
            row[5] is None
            or (
                resolved_before_ts_ms is not None
                and (
                    row[7] is None
                    or int(row[7]) > int(resolved_before_ts_ms)
                )
            )
            for row in by_horizon.values()
        ):
            stopped_pending = True
            return True
        features = json.loads(str(rows[0][2]))
        metadata = decision_metadata(str(rows[0][3]))
        if prefer_binding:
            candidate_plan = json.loads(str(rows[0][8]))
            baseline_plan = json.loads(str(rows[0][9]))
            canonical = lambda value: hashlib.sha256(json.dumps(
                value, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            metadata = {
                **metadata,
                "_authoritative_candidate_plan": candidate_plan,
                "_authoritative_baseline_plan": baseline_plan,
                "_authoritative_candidate_plan_fingerprint": canonical(
                    candidate_plan
                ),
                "_authoritative_baseline_plan_fingerprint": canonical(
                    baseline_plan
                ),
            }
        group: list[ResolvedSample] = []
        for horizon in horizons:
            row = by_horizon[horizon]
            outcome = store._outcome(str(row[5]))
            baseline = store._baseline_outcome(
                normalized_kind,
                str(row[6]) if row[6] is not None else None,
                outcome,
            )
            group.append(ResolvedSample(
                snapshot_ts_ms=snapshot,
                regime=str(features.get("regime", "UNKNOWN")),
                horizon_min=horizon,
                outcome=outcome,
                baseline_net_pnl_quote=baseline.net_pnl_quote,
                decision_metadata=metadata,
            ))
        total_independent += 1
        if prefer_binding:
            count = Decimal(len(group))
            candidate_value = sum(
                (sample.outcome.net_pnl_quote for sample in group), Decimal("0")
            ) / count
            baseline_value = sum(
                (sample.baseline_net_pnl_quote for sample in group), Decimal("0")
            ) / count
            authoritative_notional = Decimal(
                str(baseline_plan["notional_quote"])
            )
            candidate_total += candidate_value
            baseline_total += baseline_value
            edge_bps_total += (
                (candidate_value - baseline_value)
                / authoritative_notional * Decimal("10000")
            )
            candidate_equity += candidate_value
            baseline_equity += baseline_value
            candidate_peak = max(candidate_peak, candidate_equity)
            baseline_peak = max(baseline_peak, baseline_equity)
            candidate_max_drawdown = max(
                candidate_max_drawdown, candidate_peak - candidate_equity
            )
            baseline_max_drawdown = max(
                baseline_max_drawdown, baseline_peak - baseline_equity
            )
        if prefer_binding and metadata.get("binding") is True:
            total_binding += 1
            if len(binding_groups) < maximum_snapshots:
                binding_groups.append(group)
        elif prefer_binding:
            if len(nonbinding_groups) < maximum_snapshots:
                nonbinding_groups.append(group)
            else:
                discarded_nonbinding += 1
        else:
            output.extend(group)
            return len(output) // len(horizons) >= maximum_snapshots
        return False

    with store._connect() as connection:
        cursor = connection.execute(query, params)
        for raw_row in cursor:
            row = tuple(raw_row)
            snapshot = int(row[1])
            if previous_snapshot is not None and snapshot < previous_snapshot:
                raise ValueError("prediction evidence chronology is inconsistent")
            previous_snapshot = snapshot
            decision_id = str(row[0])
            if current and decision_id != str(current[0][0]):
                if consume(current):
                    break
                current = []
            current.append(row)
        else:
            consume(current)

    if prefer_binding:
        output = [
            sample
            for group in sorted(
                [*binding_groups, *nonbinding_groups],
                key=lambda item: item[0].snapshot_ts_ms,
            )
            for sample in group
        ]
    return IndependentEvidence(
        samples=tuple(output),
        scanned_snapshots=scanned,
        excluded_overlapping_snapshots=excluded,
        stopped_at_pending_snapshot=stopped_pending,
        total_independent_snapshots=total_independent,
        retained_binding_snapshots=len(binding_groups),
        discarded_nonbinding_snapshots=discarded_nonbinding,
        cohort_summary={
            "independent_snapshots": total_independent,
            "binding_snapshots": total_binding,
            "candidate_pnl_sum": format(candidate_total, "f"),
            "baseline_pnl_sum": format(baseline_total, "f"),
            "edge_bps_sum": format(edge_bps_total, "f"),
            "candidate_max_drawdown": format(candidate_max_drawdown, "f"),
            "baseline_max_drawdown": format(baseline_max_drawdown, "f"),
        },
    )


__all__ = [
    "IndependentEvidence",
    "MAX_INDEPENDENT_SNAPSHOTS",
    "resolved_independent_evidence",
]
