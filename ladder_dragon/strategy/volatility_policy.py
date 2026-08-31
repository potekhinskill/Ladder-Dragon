# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze volatility buckets before replay confirmation starts.
"""Create and verify a selection-only volatility policy."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from ladder_dragon.strategy.depth_segments import atomic_json
from ladder_dragon.strategy.market_replay import ReplayCalibration
from ladder_dragon.strategy.prediction.episode_semantics import canonical_digest
from ladder_dragon.strategy.volatility_measurement import (
    VOLATILITY_EVENT_POPULATION,
    VOLATILITY_MEASUREMENT_WINDOW_MS,
    VOLATILITY_METRIC,
)


MINIMUM_SELECTION_REPORTS = 100
MAXIMUM_SELECTION_REPORTS = 2_048
MINIMUM_SELECTION_SPAN_MS = 2 * 86_400_000
MINIMUM_SELECTION_BUCKET_REPORTS = 20
MINIMUM_CONFIRMATION_BUCKET_REPORTS = 3
MINIMUM_CONFIRMATION_SPAN_MS = 2 * 86_400_000
VOLATILITY_BUCKETS = ("low", "normal", "high")
VOLATILITY_PUBLISH_INTERVAL_MS = 5 * 60_000
MINIMUM_CALIBRATION_WINDOW_MS = 54 * 60_000
MAXIMUM_CALIBRATION_WINDOW_MS = 56 * 60_000
PREREGISTERED_LOW_MAX_BPS = Decimal("0.5")
PREREGISTERED_HIGH_MIN_BPS = Decimal("2")


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


def _bucket_counts(
    values: Iterable[Decimal], *, low_max_bps: Decimal, high_min_bps: Decimal
) -> dict[str, int]:
    counts = {"low": 0, "normal": 0, "high": 0}
    for value in values:
        bucket = (
            "low" if value <= low_max_bps
            else "high" if value >= high_min_bps
            else "normal"
        )
        counts[bucket] += 1
    return counts


def volatility_calibration_window_compatible(
    row: ReplayCalibration,
) -> bool:
    """Return true only for the measurement window frozen by the policy."""
    duration = row.last_ts_ms - row.first_ts_ms
    return (
        volatility_calibration_semantics_compatible(row)
        and MINIMUM_CALIBRATION_WINDOW_MS <= duration
        <= MAXIMUM_CALIBRATION_WINDOW_MS
    )


def volatility_calibration_semantics_compatible(
    row: ReplayCalibration,
) -> bool:
    """Return true only for the shared depth-update event population."""
    return bool(
        row.schema_version == 5
        and row.volatility_metric == VOLATILITY_METRIC
        and row.volatility_event_population == VOLATILITY_EVENT_POPULATION
        and row.volatility_measurement_window_ms
        == VOLATILITY_MEASUREMENT_WINDOW_MS
    )


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
            or not volatility_calibration_window_compatible(row)
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
    bucket_counts = _bucket_counts(
        values, low_max_bps=low_max_bps, high_min_bps=high_min_bps
    )
    boundary_policy = "ZERO_INFLATED_EMPIRICAL_TERTILES_V2"
    if high_min_bps <= low_max_bps or any(
        bucket_counts[name] < MINIMUM_SELECTION_BUCKET_REPORTS
        for name in ("low", "normal", "high")
    ):
        # Short depth segments can have a zero-inflated move distribution.
        # Split the positive tail instead of creating an empty normal bucket.
        higher = [value for value in values if value > low_max_bps]
        if len(higher) >= MINIMUM_SELECTION_BUCKET_REPORTS * 2:
            high_min_bps = _quantile(higher, 1, 2)
            bucket_counts = _bucket_counts(
                values, low_max_bps=low_max_bps,
                high_min_bps=high_min_bps,
            )
    if any(
        bucket_counts[name] < MINIMUM_SELECTION_BUCKET_REPORTS
        for name in ("low", "normal", "high")
    ):
        # These safe bounds predate the cohort. They cannot adapt to its
        # values. A bucket without selection coverage remains blocked.
        low_max_bps = PREREGISTERED_LOW_MAX_BPS
        high_min_bps = PREREGISTERED_HIGH_MIN_BPS
        bucket_counts = _bucket_counts(
            values, low_max_bps=low_max_bps, high_min_bps=high_min_bps
        )
        boundary_policy = "PREREGISTERED_SAFE_BOUNDS_V1"
    confirmable = [
        name for name in VOLATILITY_BUCKETS
        if bucket_counts[name] >= MINIMUM_SELECTION_BUCKET_REPORTS
    ]
    if boundary_policy == "PREREGISTERED_SAFE_BOUNDS_V1" and not (
        "low" in confirmable and "normal" in confirmable
    ):
        raise ValueError("volatility selection bucket coverage is insufficient")
    payload: dict[str, object] = {
        "schema_version": 5,
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
        "selection_bucket_counts": bucket_counts,
        "selection_confirmable_buckets": confirmable,
        "selection_blocked_buckets": [
            name for name in VOLATILITY_BUCKETS if name not in confirmable
        ],
        "selection_bucket_activation_policy": "bucket_scoped_fail_closed_v1",
        "minimum_selection_bucket_reports": MINIMUM_SELECTION_BUCKET_REPORTS,
        "volatility_metric": VOLATILITY_METRIC,
        "volatility_event_population": VOLATILITY_EVENT_POPULATION,
        "measurement_window_ms": VOLATILITY_MEASUREMENT_WINDOW_MS,
        "publish_interval_ms": VOLATILITY_PUBLISH_INTERVAL_MS,
        "selection_report_minimum_window_ms": (
            MINIMUM_CALIBRATION_WINDOW_MS
        ),
        "selection_report_maximum_window_ms": (
            MAXIMUM_CALIBRATION_WINDOW_MS
        ),
        "quantile_rule": boundary_policy,
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
        bucket_counts = candidate["selection_bucket_counts"]
        boundary_policy = str(candidate["quantile_rule"])
        expected_confirmable = [
            name for name in VOLATILITY_BUCKETS
            if bucket_counts[name] >= MINIMUM_SELECTION_BUCKET_REPORTS
        ]
        expected_blocked = [
            name for name in VOLATILITY_BUCKETS
            if name not in expected_confirmable
        ]
        boundary_valid = bool(
            (
                boundary_policy == "ZERO_INFLATED_EMPIRICAL_TERTILES_V2"
                and not expected_blocked
            )
            or (
                boundary_policy == "PREREGISTERED_SAFE_BOUNDS_V1"
                and low == PREREGISTERED_LOW_MAX_BPS
                and high == PREREGISTERED_HIGH_MIN_BPS
                and "low" in expected_confirmable
                and "normal" in expected_confirmable
            )
        )
        return (
            candidate.get("schema_version") == 5
            and candidate.get("mode") == "SHADOW"
            and candidate.get("apply_allowed") is False
            and candidate.get("scope") == "VOLATILITY_POLICY_SELECTION_ONLY"
            and candidate.get("volatility_metric") == VOLATILITY_METRIC
            and candidate.get("volatility_event_population")
            == VOLATILITY_EVENT_POPULATION
            and candidate.get("measurement_window_ms")
            == VOLATILITY_MEASUREMENT_WINDOW_MS
            and candidate.get("publish_interval_ms")
            == VOLATILITY_PUBLISH_INTERVAL_MS
            and candidate.get("selection_report_minimum_window_ms")
            == MINIMUM_CALIBRATION_WINDOW_MS
            and candidate.get("selection_report_maximum_window_ms")
            == MAXIMUM_CALIBRATION_WINDOW_MS
            and boundary_valid
            and candidate.get("selection_bucket_activation_policy")
            == "bucket_scoped_fail_closed_v1"
            and candidate.get("selection_confirmable_buckets")
            == expected_confirmable
            and candidate.get("selection_blocked_buckets")
            == expected_blocked
            and candidate.get("confirmation_reuses_selection") is False
            and count >= MINIMUM_SELECTION_REPORTS
            and count <= MAXIMUM_SELECTION_REPORTS
            and cutoff > 0
            and low.is_finite()
            and high.is_finite()
            and low >= 0
            and high > low
            and candidate.get("minimum_selection_bucket_reports")
            == MINIMUM_SELECTION_BUCKET_REPORTS
            and isinstance(bucket_counts, dict)
            and set(bucket_counts) == {"low", "normal", "high"}
            and all(
                type(bucket_counts[name]) is int
                and bucket_counts[name] >= 0
                for name in VOLATILITY_BUCKETS
            )
            and sum(bucket_counts.values()) == count
            and len(archives) == len(set(archives)) == count
            and len(reports) == len(set(reports)) == count
            and all(len(str(item)) == 64 for item in archives + reports)
            and len(observed) == 64
            and observed == canonical_digest(candidate)
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def _verify_legacy_volatility_policy(payload: Mapping[str, object]) -> bool:
    """Verify the exact schema-2 policy before a deterministic migration."""
    candidate = dict(payload)
    observed = str(candidate.pop("policy_sha256", ""))
    try:
        legacy_fields = {
            "schema_version", "mode", "apply_allowed", "scope",
            "cutoff_ts_ms", "created_at_ms", "selection_report_count",
            "selection_first_ts_ms", "selection_last_ts_ms",
            "selection_archive_sha256s", "selection_report_sha256s",
            "low_max_bps", "high_min_bps", "selection_bucket_counts",
            "minimum_selection_bucket_reports", "volatility_metric",
            "quantile_rule", "confirmation_reuses_selection",
        }
        low = Decimal(str(candidate["low_max_bps"]))
        high = Decimal(str(candidate["high_min_bps"]))
        count = int(candidate["selection_report_count"])
        archives = tuple(candidate["selection_archive_sha256s"])
        reports = tuple(candidate["selection_report_sha256s"])
        buckets = candidate["selection_bucket_counts"]
        return (
            set(candidate) == legacy_fields
            and candidate.get("schema_version") == 2
            and candidate.get("mode") == "SHADOW"
            and candidate.get("apply_allowed") is False
            and candidate.get("scope") == "VOLATILITY_POLICY_SELECTION_ONLY"
            and candidate.get("volatility_metric")
            == "CALIBRATION_EVENT_MOVE_P95_BPS"
            and candidate.get("quantile_rule")
            == "ZERO_INFLATED_EMPIRICAL_TERTILES_V2"
            and candidate.get("confirmation_reuses_selection") is False
            and MINIMUM_SELECTION_REPORTS <= count <= MAXIMUM_SELECTION_REPORTS
            and int(candidate["cutoff_ts_ms"]) > 0
            and low.is_finite() and high.is_finite()
            and low >= 0 and high > low
            and candidate.get("minimum_selection_bucket_reports")
            == MINIMUM_SELECTION_BUCKET_REPORTS
            and isinstance(buckets, dict)
            and set(buckets) == set(VOLATILITY_BUCKETS)
            and all(
                type(buckets[name]) is int
                and buckets[name] >= MINIMUM_SELECTION_BUCKET_REPORTS
                for name in VOLATILITY_BUCKETS
            )
            and sum(buckets.values()) == count
            and len(archives) == len(set(archives)) == count
            and len(reports) == len(set(reports)) == count
            and all(len(str(item)) == 64 for item in archives + reports)
            and len(observed) == 64
            and observed == canonical_digest(candidate)
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def _verify_schema4_volatility_policy(payload: Mapping[str, object]) -> bool:
    """Verify the previous event-population policy before reselection."""
    candidate = dict(payload)
    observed = str(candidate.pop("policy_sha256", ""))
    try:
        count = int(candidate["selection_report_count"])
        archives = tuple(candidate["selection_archive_sha256s"])
        reports = tuple(candidate["selection_report_sha256s"])
        buckets = candidate["selection_bucket_counts"]
        confirmable = candidate["selection_confirmable_buckets"]
        blocked = candidate["selection_blocked_buckets"]
        return bool(
            candidate.get("schema_version") == 4
            and candidate.get("mode") == "SHADOW"
            and candidate.get("apply_allowed") is False
            and candidate.get("scope") == "VOLATILITY_POLICY_SELECTION_ONLY"
            and candidate.get("volatility_metric")
            == "EVENT_MOVE_P95_BPS_OVER_55_MINUTES_V1"
            and candidate.get("measurement_window_ms")
            == VOLATILITY_MEASUREMENT_WINDOW_MS
            and candidate.get("publish_interval_ms")
            == VOLATILITY_PUBLISH_INTERVAL_MS
            and candidate.get("confirmation_reuses_selection") is False
            and MINIMUM_SELECTION_REPORTS <= count <= MAXIMUM_SELECTION_REPORTS
            and int(candidate["cutoff_ts_ms"]) > 0
            and isinstance(buckets, dict)
            and set(buckets) == set(VOLATILITY_BUCKETS)
            and sum(int(buckets[name]) for name in VOLATILITY_BUCKETS) == count
            and set(confirmable) | set(blocked) == set(VOLATILITY_BUCKETS)
            and not set(confirmable) & set(blocked)
            and len(archives) == len(set(archives)) == count
            and len(reports) == len(set(reports)) == count
            and all(len(str(item)) == 64 for item in archives + reports)
            and len(observed) == 64
            and observed == canonical_digest(candidate)
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def migrate_legacy_volatility_policy(
    policy_path: Path,
    report_directory: Path,
) -> dict[str, object]:
    """Migrate one valid prior policy without changing its source cohort."""
    legacy = _read_payload(policy_path)
    if verify_volatility_policy(legacy):
        return legacy
    legacy_schema = int(legacy.get("schema_version", 0))
    schema2 = _verify_legacy_volatility_policy(legacy)
    schema4 = _verify_schema4_volatility_policy(legacy)
    if not (schema2 or schema4):
        raise ValueError("legacy volatility policy is invalid")
    required_hashes = set(legacy["selection_report_sha256s"])
    required_archives = set(legacy["selection_archive_sha256s"])
    matched: dict[str, Path] = {}
    for index, path in enumerate(sorted(report_directory.glob("*.calibration.json"))):
        if index >= MAXIMUM_SELECTION_REPORTS * 4:
            raise ValueError("volatility report migration capacity reached")
        if schema2:
            identity = _file_sha256(path)
        else:
            row = ReplayCalibration.from_dict(_read_payload(path))
            if not volatility_calibration_window_compatible(row):
                continue
            identity = row.archive_sha256
        required = required_hashes if schema2 else required_archives
        if identity in required:
            matched[identity] = path
    required = required_hashes if schema2 else required_archives
    if set(matched) != required:
        raise ValueError("legacy volatility selection sources are unavailable")
    migrated = select_volatility_policy(
        [matched[digest] for digest in sorted(required)],
        cutoff_ts_ms=int(legacy["cutoff_ts_ms"]),
        created_at_ms=int(legacy["created_at_ms"]),
    )
    immutable_fields = (
        "cutoff_ts_ms", "created_at_ms", "selection_report_count",
        "selection_first_ts_ms", "selection_last_ts_ms",
        "selection_archive_sha256s",
    )
    if schema2:
        immutable_fields += (
            "selection_report_sha256s", "low_max_bps", "high_min_bps",
            "selection_bucket_counts",
        )
    if any(migrated[field] != legacy[field] for field in immutable_fields):
        raise ValueError("legacy volatility policy migration changed selection")
    legacy_hash = str(legacy["policy_sha256"])
    archive_path = policy_path.with_name(
        f"volatility-policy.schema{legacy_schema}-{legacy_hash}.json"
    )
    if archive_path.exists():
        if _read_payload(archive_path) != legacy:
            raise ValueError("legacy volatility policy archive differs")
    else:
        descriptor = os.open(
            archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(legacy, target, sort_keys=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
    atomic_json(policy_path, migrated, replace=True)
    return migrated


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
    if any(not volatility_calibration_window_compatible(row) for row in rows):
        reasons.append("volatility confirmation window differs from policy")
    return tuple(reasons)


def confirmed_volatility_scope(
    policy: Mapping[str, object],
    calibrations: Iterable[ReplayCalibration],
) -> dict[str, object]:
    """Freeze only post-cutoff volatility buckets with sufficient coverage."""
    rows = list(calibrations)
    reasons = confirmation_cohort_reasons(policy, rows)
    if reasons:
        raise ValueError("volatility confirmation cohort is invalid")
    if not rows:
        raise ValueError("volatility confirmation cohort is empty")
    if (
        any(not row.eligible for row in rows)
        or len({row.archive_sha256 for row in rows}) != len(rows)
    ):
        raise ValueError("volatility confirmation cohort is ineligible")
    first = min(row.first_ts_ms for row in rows)
    last = max(row.last_ts_ms for row in rows)
    if last - first < MINIMUM_CONFIRMATION_SPAN_MS:
        raise ValueError("volatility confirmation span is insufficient")
    low = Decimal(str(policy["low_max_bps"]))
    high = Decimal(str(policy["high_min_bps"]))
    counts = _bucket_counts(
        (row.volatility_bps_p95 for row in rows),
        low_max_bps=low,
        high_min_bps=high,
    )
    confirmed = [
        name for name in VOLATILITY_BUCKETS
        if name in policy["selection_confirmable_buckets"]
        and counts[name] >= MINIMUM_CONFIRMATION_BUCKET_REPORTS
    ]
    if not confirmed:
        raise ValueError("no volatility bucket has confirmation coverage")
    payload: dict[str, object] = {
        "schema_version": 1,
        "scope": "POST_CUTOFF_VOLATILITY_BUCKET_ACTIVATION",
        "apply_allowed": False,
        "volatility_policy_sha256": str(policy["policy_sha256"]),
        "selection_cutoff_ts_ms": int(policy["cutoff_ts_ms"]),
        "confirmation_first_ts_ms": first,
        "confirmation_last_ts_ms": last,
        "confirmation_span_ms": last - first,
        "minimum_confirmation_span_ms": MINIMUM_CONFIRMATION_SPAN_MS,
        "minimum_confirmation_bucket_reports": (
            MINIMUM_CONFIRMATION_BUCKET_REPORTS
        ),
        "confirmation_bucket_counts": counts,
        "confirmed_buckets": confirmed,
        "blocked_buckets": [
            name for name in VOLATILITY_BUCKETS if name not in confirmed
        ],
        "confirmation_archive_sha256s": sorted(
            row.archive_sha256 for row in rows
        ),
    }
    payload["scope_sha256"] = canonical_digest(payload)
    return payload


def verify_volatility_scope(
    payload: Mapping[str, object], *, policy: Mapping[str, object]
) -> bool:
    """Verify a bucket-scoped confirmation without expanding its permissions."""
    candidate = dict(payload)
    observed = str(candidate.pop("scope_sha256", ""))
    try:
        confirmed = tuple(candidate["confirmed_buckets"])
        blocked = tuple(candidate["blocked_buckets"])
        counts = candidate["confirmation_bucket_counts"]
        archives = tuple(candidate["confirmation_archive_sha256s"])
        return (
            verify_volatility_policy(policy)
            and candidate.get("schema_version") == 1
            and candidate.get("scope")
            == "POST_CUTOFF_VOLATILITY_BUCKET_ACTIVATION"
            and candidate.get("apply_allowed") is False
            and candidate.get("volatility_policy_sha256")
            == policy.get("policy_sha256")
            and int(candidate["selection_cutoff_ts_ms"])
            == int(policy["cutoff_ts_ms"])
            and int(candidate["confirmation_first_ts_ms"])
            > int(policy["cutoff_ts_ms"])
            and int(candidate["confirmation_last_ts_ms"])
            >= int(candidate["confirmation_first_ts_ms"])
            and int(candidate["confirmation_span_ms"])
            >= MINIMUM_CONFIRMATION_SPAN_MS
            and candidate.get("minimum_confirmation_span_ms")
            == MINIMUM_CONFIRMATION_SPAN_MS
            and candidate.get("minimum_confirmation_bucket_reports")
            == MINIMUM_CONFIRMATION_BUCKET_REPORTS
            and isinstance(counts, dict)
            and set(counts) == set(VOLATILITY_BUCKETS)
            and all(type(counts[name]) is int and counts[name] >= 0 for name in VOLATILITY_BUCKETS)
            and confirmed
            and set(confirmed).isdisjoint(blocked)
            and set(confirmed) | set(blocked) == set(VOLATILITY_BUCKETS)
            and list(confirmed) == [
                name for name in VOLATILITY_BUCKETS
                if name in policy["selection_confirmable_buckets"]
                and int(counts[name]) >= MINIMUM_CONFIRMATION_BUCKET_REPORTS
            ]
            and list(blocked) == [
                name for name in VOLATILITY_BUCKETS if name not in confirmed
            ]
            and len(archives) == len(set(archives))
            and sum(int(counts[name]) for name in VOLATILITY_BUCKETS)
            == len(archives)
            and all(len(str(item)) == 64 for item in archives)
            and len(observed) == 64
            and observed == canonical_digest(candidate)
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


__all__ = [
    "confirmed_volatility_scope",
    "confirmation_cohort_reasons",
    "migrate_legacy_volatility_policy",
    "read_volatility_policy",
    "select_volatility_policy",
    "volatility_calibration_window_compatible",
    "verify_volatility_scope",
    "verify_volatility_policy",
]
