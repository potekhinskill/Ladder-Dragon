# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: limit disposable legacy prediction evidence with durable buckets.
"""Restart-safe cadence for derived LEGACY prediction snapshots."""

LEGACY_EVIDENCE_CADENCE_MS = 300_000


class LegacyEvidenceCadenceMixin:
    """Provide a durable cadence query to a prediction SQLite store."""

    def legacy_snapshot_due(
        self,
        *,
        kind: str,
        symbol: str,
        snapshot_ts_ms: int,
        cadence_ms: int = LEGACY_EVIDENCE_CADENCE_MS,
    ) -> bool:
        """Limit derived snapshots without changing experiment evidence."""
        if (
            type(snapshot_ts_ms) is not int
            or type(cadence_ms) is not int
            or snapshot_ts_ms <= 0
            or cadence_ms < 60_000
            or cadence_ms > 3_600_000
        ):
            raise ValueError("legacy evidence cadence is invalid")
        normalized_kind = str(kind).upper()
        if normalized_kind != "STRATEGY" and not normalized_kind.startswith(
            "CONTROL_"
        ):
            raise ValueError("legacy cadence kind is unsupported")
        bucket_start = snapshot_ts_ms // cadence_ms * cadence_ms
        with self._connect() as connection:
            found = connection.execute(
                """SELECT 1 FROM prediction_decisions
                   WHERE kind=? AND symbol=? AND evidence_role='LEGACY'
                     AND snapshot_ts_ms>=? AND snapshot_ts_ms<? LIMIT 1""",
                (
                    normalized_kind,
                    symbol.upper(),
                    bucket_start,
                    bucket_start + cadence_ms,
                ),
            ).fetchone()
        return found is None


__all__ = ["LEGACY_EVIDENCE_CADENCE_MS", "LegacyEvidenceCadenceMixin"]
