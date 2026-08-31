# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind replay proof to separate order and read-only calibration cohorts.
"""Create immutable identities for replay calibration context."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Mapping

from ladder_dragon.strategy.market_replay import ReplayCalibration
from ladder_dragon.strategy.prediction.episode_semantics import canonical_digest


def calibration_context_evidence(
    calibrations: Iterable[ReplayCalibration],
    *,
    readiness: Mapping[str, object],
    volatility_policy: Mapping[str, object] | None = None,
    volatility_scope: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Fingerprint read-only archives without claiming order coverage."""
    rows = sorted(calibrations, key=lambda item: item.archive_sha256)
    hashes = [row.archive_sha256 for row in rows]
    if not rows or len(set(hashes)) != len(hashes):
        raise ValueError("calibration context identity is invalid")
    first = min(row.first_ts_ms for row in rows)
    last = max(row.last_ts_ms for row in rows)
    payload: dict[str, object] = {
        "schema_version": 1,
        "scope": "READ_ONLY_CALIBRATION_CONTEXT",
        "archive_sha256s": hashes,
        "first_ts_ms": first,
        "last_ts_ms": last,
        "span_days": format(
            Decimal(last - first) / Decimal("86400000"), "f"
        ),
        "readiness": dict(readiness),
        "volatility_policy": (
            dict(volatility_policy) if volatility_policy is not None else None
        ),
        "volatility_scope": (
            dict(volatility_scope) if volatility_scope is not None else None
        ),
    }
    payload["cohort_sha256"] = canonical_digest(payload)
    return payload


def verify_cohort_fingerprint(payload: Mapping[str, object]) -> bool:
    """Verify one cohort fingerprint without mutating its source mapping."""
    candidate = dict(payload)
    observed = str(candidate.pop("cohort_sha256", ""))
    return len(observed) == 64 and observed == canonical_digest(candidate)


__all__ = ["calibration_context_evidence", "verify_cohort_fingerprint"]
