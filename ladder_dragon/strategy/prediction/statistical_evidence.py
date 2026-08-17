# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: stream independent statistical evidence without loading full history.

"""Bounded-memory access to immutable, non-overlapping prediction evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Sequence

from ladder_dragon.strategy.prediction.models import ResolvedSample
from ladder_dragon.strategy.prediction.statistical_units import outcome_spacing_ms


MAX_INDEPENDENT_SNAPSHOTS = 512


@dataclass(frozen=True)
class IndependentEvidence:
    """A chronological prefix of complete, independent decision snapshots."""

    samples: tuple[ResolvedSample, ...]
    scanned_snapshots: int
    excluded_overlapping_snapshots: int
    stopped_at_pending_snapshot: bool


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
) -> IndependentEvidence:
    """Stream the full cohort and retain only a stable independent prefix."""
    horizons = tuple(int(value) for value in required_horizons_min)
    if not horizons or tuple(sorted(set(horizons))) != horizons:
        raise ValueError("statistical horizons must be unique and increasing")
    if maximum_snapshots <= 0:
        raise ValueError("maximum statistical snapshots must be positive")
    normalized_kind = str(kind).upper()
    query = """SELECT d.decision_id,d.snapshot_ts_ms,d.feature_json,
                      o.horizon_min,o.outcome_json,o.baseline_outcome_json,
                      o.resolved_at_ms
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

    def consume(rows: list[tuple[object, ...]]) -> bool:
        nonlocal scanned, excluded, stopped_pending, next_allowed_ms
        if not rows:
            return False
        snapshot = int(rows[0][1])
        scanned += 1
        if next_allowed_ms is not None and snapshot < next_allowed_ms:
            excluded += 1
            return False
        next_allowed_ms = snapshot + outcome_spacing_ms(horizons)
        by_horizon = {int(row[3]): row for row in rows}
        if tuple(sorted(by_horizon)) != horizons:
            stopped_pending = True
            return True
        if any(
            row[4] is None
            or (
                resolved_before_ts_ms is not None
                and (
                    row[6] is None
                    or int(row[6]) > int(resolved_before_ts_ms)
                )
            )
            for row in by_horizon.values()
        ):
            stopped_pending = True
            return True
        features = json.loads(str(rows[0][2]))
        for horizon in horizons:
            row = by_horizon[horizon]
            outcome = store._outcome(str(row[4]))
            baseline = store._baseline_outcome(
                normalized_kind,
                str(row[5]) if row[5] is not None else None,
                outcome,
            )
            output.append(ResolvedSample(
                snapshot_ts_ms=snapshot,
                regime=str(features.get("regime", "UNKNOWN")),
                horizon_min=horizon,
                outcome=outcome,
                baseline_net_pnl_quote=baseline.net_pnl_quote,
            ))
        return len(output) // len(horizons) >= maximum_snapshots

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

    return IndependentEvidence(
        samples=tuple(output),
        scanned_snapshots=scanned,
        excluded_overlapping_snapshots=excluded,
        stopped_at_pending_snapshot=stopped_pending,
    )


__all__ = [
    "IndependentEvidence",
    "MAX_INDEPENDENT_SNAPSHOTS",
    "resolved_independent_evidence",
]
