# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze volatility buckets before replay confirmation starts.
"""Create and verify a selection-only volatility policy."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from ladder_dragon.strategy.market_replay import ReplayCalibration
from ladder_dragon.strategy.prediction.episode_semantics import canonical_digest


MINIMUM_SELECTION_REPORTS = 100
MAXIMUM_SELECTION_REPORTS = 2_048
MINIMUM_SELECTION_SPAN_MS = 2 * 86_400_000


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_payload(path: Path) -> dict[str, object]:
    if path.stat().st_size > 512 * 1024:
        raise ValueError("volatility calibration report is too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("volatility calibration report must be an object")
    return payload


def _quantile(values: list[Decimal], numerator: int, denominator: int) -> Decimal:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) * numerator // denominator]


def select_volatility_policy(
    report_paths: Iterable[Path],
    *,
    cutoff_ts_ms: int,
    created_at_ms: int,
) -> dict[str, object]:
    """Freeze empirical bucket boundaries from the pre-cutoff cohort."""
    if cutoff_ts_ms <= 0 or created_at_ms < cutoff_ts_ms:
        raise ValueError("volatility selection timestamps are invalid")
    rows: list[tuple[ReplayCalibration, str]] = []
    report_hashes: list[str] = []
    for path in report_paths:
        payload = _read_payload(path)
        row = ReplayCalibration.from_dict(payload)
        report_hash = _file_sha256(path)
        if (
            not row.eligible
            or row.last_ts_ms > cutoff_ts_ms
            or len(row.archive_sha256) != 64
            or len(report_hash) != 64
        ):
            raise ValueError("volatility selection report is ineligible")
        rows.append((row, report_hash))
        report_hashes.append(report_hash)
    archive_hashes = [row.archive_sha256 for row, _digest in rows]
    if (
        len(rows) < MINIMUM_SELECTION_REPORTS
        or len(rows) > MAXIMUM_SELECTION_REPORTS
        or len(set(archive_hashes)) != len(rows)
        or len(set(report_hashes)) != len(rows)
    ):
        raise ValueError("volatility selection cohort is insufficient")
    first_ts_ms = min(row.first_ts_ms for row, _digest in rows)
    last_ts_ms = max(row.last_ts_ms for row, _digest in rows)
    if last_ts_ms - first_ts_ms < MINIMUM_SELECTION_SPAN_MS:
        raise ValueError("volatility selection span is insufficient")
    values = [row.volatility_bps_p95 for row, _digest in rows]
    if any(not value.is_finite() or value < 0 for value in values):
        raise ValueError("volatility selection values are invalid")
    low_max_bps = _quantile(values, 1, 3)
    high_min_bps = _quantile(values, 2, 3)
    if high_min_bps <= low_max_bps:
        higher = sorted({value for value in values if value > low_max_bps})
        if not higher:
            raise ValueError("volatility selection has no separable buckets")
        high_min_bps = higher[0]
    payload: dict[str, object] = {
        "schema_version": 1,
        "mode": "SHADOW",
        "apply_allowed": False,
        "scope": "VOLATILITY_POLICY_SELECTION_ONLY",
        "cutoff_ts_ms": cutoff_ts_ms,
        "created_at_ms": created_at_ms,
        "selection_report_count": len(rows),
        "selection_first_ts_ms": first_ts_ms,
        "selection_last_ts_ms": last_ts_ms,
        "selection_archive_sha256s": sorted(archive_hashes),
        "selection_report_sha256s": sorted(report_hashes),
        "low_max_bps": format(low_max_bps, "f"),
        "high_min_bps": format(high_min_bps, "f"),
        "quantile_rule": "EMPIRICAL_TERTILES_V1",
        "confirmation_reuses_selection": False,
    }
    payload["policy_sha256"] = canonical_digest(payload)
    return payload


def verify_volatility_policy(payload: Mapping[str, object]) -> bool:
    """Verify the immutable selection policy and its fail-closed bounds."""
    candidate = dict(payload)
    observed = str(candidate.pop("policy_sha256", ""))
    try:
        low = Decimal(str(candidate["low_max_bps"]))
        high = Decimal(str(candidate["high_min_bps"]))
        cutoff = int(candidate["cutoff_ts_ms"])
        archives = tuple(candidate["selection_archive_sha256s"])
        reports = tuple(candidate["selection_report_sha256s"])
        count = int(candidate["selection_report_count"])
        return (
            candidate.get("schema_version") == 1
            and candidate.get("mode") == "SHADOW"
            and candidate.get("apply_allowed") is False
            and candidate.get("scope") == "VOLATILITY_POLICY_SELECTION_ONLY"
            and candidate.get("quantile_rule") == "EMPIRICAL_TERTILES_V1"
            and candidate.get("confirmation_reuses_selection") is False
            and count >= MINIMUM_SELECTION_REPORTS
            and count <= MAXIMUM_SELECTION_REPORTS
            and cutoff > 0
            and low.is_finite()
            and high.is_finite()
            and low >= 0
            and high > low
            and len(archives) == len(set(archives)) == count
            and len(reports) == len(set(reports)) == count
            and all(len(str(item)) == 64 for item in archives + reports)
            and len(observed) == 64
            and observed == canonical_digest(candidate)
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def read_volatility_policy(path: Path) -> dict[str, object]:
    payload = _read_payload(path)
    if not verify_volatility_policy(payload):
        raise ValueError("volatility policy is invalid")
    return payload


def confirmation_cohort_reasons(
    policy: Mapping[str, object],
    calibrations: Iterable[ReplayCalibration],
) -> tuple[str, ...]:
    """Prove that confirmation starts after the frozen selection cutoff."""
    if not verify_volatility_policy(policy):
        return ("volatility policy is invalid",)
    rows = list(calibrations)
    cutoff = int(policy["cutoff_ts_ms"])
    selection_hashes = set(policy["selection_archive_sha256s"])
    observed_hashes = {row.archive_sha256 for row in rows}
    reasons: list[str] = []
    if any(row.first_ts_ms <= cutoff for row in rows):
        reasons.append("volatility confirmation starts before the cutoff")
    if selection_hashes & observed_hashes:
        reasons.append("volatility selection and confirmation overlap")
    return tuple(reasons)


__all__ = [
    "confirmation_cohort_reasons",
    "read_volatility_policy",
    "select_volatility_policy",
    "verify_volatility_policy",
]
