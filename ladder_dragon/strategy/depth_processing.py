# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: process finalized public segments outside the recording process.
"""Bounded calibration backlog and truthful public-context coverage status."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import time

from ladder_dragon.strategy.depth_segments import (
    MAX_SEGMENTS, atomic_json, bounded_json, iter_segment_events, verified_segments,
)
from ladder_dragon.strategy.market_replay import ReplayCalibration, calibrate_market_events
from ladder_dragon.strategy.replay_policy import PRODUCTION_REPLAY_ACCEPTANCE_POLICY
from ladder_dragon.strategy.replay_readiness import volatility_regime
from ladder_dragon.strategy.volatility_policy import (
    MINIMUM_CONFIRMATION_BUCKET_REPORTS,
    VOLATILITY_BUCKETS,
    migrate_legacy_volatility_policy,
    read_volatility_policy,
    volatility_calibration_semantics_compatible,
    volatility_calibration_window_compatible,
    volatility_policy_migration_readiness,
    volatility_policy_source_contract,
)


VOLATILITY_CONFIRMATION_SPAN_MS = 2 * 86_400_000


def _metadata_start_ms(metadata: dict[str, object]) -> int:
    value = metadata.get("started_at_ms")
    return value if type(value) is int and value >= 0 else 0


def _attach_migration_eta(
    status: dict[str, object], average_seconds: float | None
) -> None:
    """Publish a bounded ETA only after one measured calibration completes."""
    migration = status.get("volatility_policy_migration")
    if not isinstance(migration, dict):
        return
    required = int(migration.get("selection_sources_required", 0))
    ready = int(migration.get("selection_sources_ready", 0))
    remaining = max(0, required - ready)
    migration["selection_sources_remaining"] = remaining
    migration["average_calibration_seconds"] = (
        round(average_seconds, 3) if average_seconds is not None else None
    )
    migration["estimated_seconds_remaining"] = (
        int(remaining * average_seconds + 0.999)
        if average_seconds is not None else None
    )


def _frozen_volatility_status(
    directory: Path, rows: list[ReplayCalibration]
) -> dict[str, object]:
    """Measure a disjoint post-cutoff cohort against one frozen policy."""
    path = directory / ".historical-replay" / "volatility-policy.json"
    if not path.is_file():
        return {
            "status": "WAITING_SELECTION_POLICY",
            "policy_sha256": None,
            "confirmation_report_count": 0,
        }
    try:
        policy = read_volatility_policy(path)
    except (OSError, ValueError):
        return {
            "status": "POLICY_RESELECTION_REQUIRED",
            "policy_sha256": None,
            "confirmation_report_count": 0,
        }
    cutoff = int(policy["cutoff_ts_ms"])
    selection = set(policy["selection_archive_sha256s"])
    confirmation = [
        row for row in rows
        if row.first_ts_ms > cutoff
        and row.archive_sha256 not in selection
        and row.eligible
        and volatility_calibration_window_compatible(row)
    ]
    low = Decimal(str(policy["low_max_bps"]))
    high = Decimal(str(policy["high_min_bps"]))
    counts = {"low": 0, "normal": 0, "high": 0}
    for row in confirmation:
        bucket = (
            "low" if row.volatility_bps_p95 <= low
            else "high" if row.volatility_bps_p95 >= high
            else "normal"
        )
        counts[bucket] += 1
    span = (
        max(row.last_ts_ms for row in confirmation)
        - min(row.first_ts_ms for row in confirmation)
        if confirmation else 0
    )
    confirmed = [
        name for name in VOLATILITY_BUCKETS
        if name in policy["selection_confirmable_buckets"]
        and span >= VOLATILITY_CONFIRMATION_SPAN_MS
        and counts[name] >= MINIMUM_CONFIRMATION_BUCKET_REPORTS
    ]
    latest = max(confirmation, key=lambda row: row.last_ts_ms, default=None)
    latest_bucket = (
        "low" if latest is not None and latest.volatility_bps_p95 <= low
        else "high" if latest is not None and latest.volatility_bps_p95 >= high
        else "normal" if latest is not None else None
    )
    return {
        "status": (
            "PASS_SCOPED"
            if confirmed else "COLLECTING_DISJOINT_CONFIRMATION"
        ),
        "policy_sha256": policy["policy_sha256"],
        "selection_cutoff_ts_ms": cutoff,
        "confirmation_report_count": len(confirmation),
        "confirmation_span_ms": span,
        "required_confirmation_span_ms": VOLATILITY_CONFIRMATION_SPAN_MS,
        "confirmation_bucket_counts": counts,
        "minimum_confirmation_bucket_reports": (
            MINIMUM_CONFIRMATION_BUCKET_REPORTS
        ),
        "confirmed_buckets": confirmed,
        "blocked_buckets": [
            name for name in VOLATILITY_BUCKETS if name not in confirmed
        ],
        "latest_bucket": latest_bucket,
        "latest_bucket_last_ts_ms": (
            latest.last_ts_ms if latest is not None else None
        ),
        "selection_sources_reused": False,
    }


def calibration_inventory(directory: Path) -> tuple[dict, list[Path]]:
    """Distinguish missing reports from genuinely absent volatility regimes."""
    missing: list[Path] = []
    regimes: Counter = Counter()
    archived = reports = invalid = ineligible = stale = 0
    sidecars = []
    metadata_by_archive: dict[Path, dict[str, object]] = {}
    eligible_rows: list[ReplayCalibration] = []
    for sidecar in directory.glob("*.jsonl.metadata.json"):
        if len(sidecars) >= MAX_SEGMENTS:
            raise ValueError("public archive inventory capacity reached")
        sidecars.append(sidecar)
    for sidecar in sorted(sidecars):
        archived += 1
        if archived > MAX_SEGMENTS:
            raise ValueError("public archive inventory capacity reached")
        archive = sidecar.with_suffix("").with_suffix("")
        report_path = archive.with_suffix(".calibration.json")
        try:
            metadata = bounded_json(sidecar)
            if not archive.is_file() or metadata.get("contains_secrets") is not False:
                raise ValueError("public archive unavailable")
            metadata_by_archive[archive] = metadata
            if not report_path.exists():
                missing.append(archive)
                continue
            payload = bounded_json(report_path)
            if type(payload.get("eligible")) is not bool:
                raise ValueError("calibration eligibility must be boolean")
            report = ReplayCalibration.from_dict(payload)
            if report.archive_sha256 != metadata["archive_sha256"]:
                raise ValueError("calibration source mismatch")
            if not volatility_calibration_semantics_compatible(report):
                stale += 1
                missing.append(archive)
                continue
            reports += 1
            if report.eligible:
                eligible_rows.append(report)
                regimes[volatility_regime(report.volatility_bps_p95)] += 1
            else:
                ineligible += 1
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
            invalid += 1
    policy_path = directory / ".historical-replay" / "volatility-policy.json"
    migration_status: dict[str, object] = {
        "schema_version": 1,
        "status": "WAITING_SELECTION_POLICY",
        "migration_required": False,
        "source_policy_schema_version": None,
        "selection_sources_ready": 0,
        "selection_sources_required": 0,
    }
    required_archives: frozenset[str] = frozenset()
    cutoff_ts_ms = 0
    if policy_path.is_file():
        try:
            migration_status = volatility_policy_migration_readiness(
                policy_path, directory
            )
            required_archives, cutoff_ts_ms = (
                volatility_policy_source_contract(policy_path)
            )
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
            migration_status = {
                **migration_status,
                "status": "POLICY_RESELECTION_REQUIRED",
                "migration_required": True,
            }
    missing.sort(key=lambda archive: (
        0
        if str(metadata_by_archive.get(archive, {}).get("archive_sha256", ""))
        in required_archives
        else 1
        if _metadata_start_ms(metadata_by_archive.get(archive, {})) > cutoff_ts_ms
        else 2,
        archive.name,
    ))
    absent = [name for name in ("low", "normal", "high") if not regimes[name]]
    frozen_status = _frozen_volatility_status(directory, eligible_rows)
    overall_status = (
        "BACKLOG_INCOMPLETE" if missing or invalid
        else str(frozen_status["status"])
        if frozen_status["status"] != "WAITING_SELECTION_POLICY"
        else "BUCKET_COVERAGE_INCOMPLETE" if absent
        else "REGIMES_COVERED"
    )
    return {
        "schema_version": 1, "mode": "SHADOW", "apply_allowed": False,
        "updated_at_ms": int(time.time() * 1000),
        "status": overall_status,
        "archives": archived, "calibration_reports": reports,
        "missing_calibrations": len(missing), "invalid_artifacts": invalid,
        "stale_calibrations": stale,
        "ineligible_calibrations": ineligible, "eligible_regime_counts": dict(regimes),
        "missing_volatility_regimes": absent,
        "high_coverage_conclusion": (
            "BACKLOG_NOT_CALIBRATED" if not regimes["high"] and missing
            else "NOT_OBSERVED" if not regimes["high"] else "OBSERVED"
        ),
        "order_validation_proven": False,
        "volatility_policy_migration": migration_status,
        "frozen_volatility_policy": frozen_status,
    }, missing


def calibrate_segment(archive: Path) -> None:
    """Produce one reproducible derived report from an immutable source."""
    segments = verified_segments([archive])
    policy = PRODUCTION_REPLAY_ACCEPTANCE_POLICY
    report = calibrate_market_events(
        iter_segment_events(segments, exchange_clock=True),
        source_sha256=segments[0][1]["archive_sha256"],
        min_book_events=policy.minimum_book_events, min_trades=policy.minimum_trades,
    )
    report_path = archive.with_suffix(".calibration.json")
    replace = False
    if report_path.exists():
        existing = ReplayCalibration.from_dict(bounded_json(report_path))
        if volatility_calibration_semantics_compatible(existing):
            raise FileExistsError(report_path)
        replace = True
    atomic_json(report_path, report.as_dict(), replace=replace)


def _run_offline(arguments: list[str], stop, *, timeout_seconds: int = 300) -> int:
    with subprocess.Popen([sys.executable, "-m", *arguments],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
        deadline = time.monotonic() + timeout_seconds
        while child.poll() is None and not stop.wait(1):
            if time.monotonic() >= deadline:
                child.kill()
                break
        if child.poll() is None:
            child.terminate()
        try:
            return child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            return child.wait()


def process_backlog(directory: Path, stop, prediction_db: Path | None = None) -> None:
    """Use one bounded child; slow calibration cannot stall the WebSocket."""
    retry_after: dict[Path, float] = {}
    next_import = 0.0
    next_historical_replay = 0.0
    next_historical_plan = 0.0
    average_calibration_seconds: float | None = None
    while not stop.is_set():
        try:
            status, pending = calibration_inventory(directory)
            migration = status["volatility_policy_migration"]
            if migration["status"] == "READY_FOR_MIGRATION":
                policy_path = (
                    directory / ".historical-replay" / "volatility-policy.json"
                )
                migrate_legacy_volatility_policy(policy_path, directory)
                status, pending = calibration_inventory(directory)
            _attach_migration_eta(status, average_calibration_seconds)
            atomic_json(directory / "calibration_inventory.json", status, replace=True)
            if prediction_db is not None and prediction_db.is_file() and time.monotonic() >= next_import:
                # Preserve the existing diagnostic importer, but run it away
                # from capture. Late terminal outcomes receive another pass.
                code = _run_offline(["bin.import_entry_veto_l2", "--prediction-db", str(prediction_db),
                                     "--archive-directory", str(directory)], stop)
                next_import = time.monotonic() + 900
                if code:
                    print(f"[DEPTH-IMPORT] status=RETRY exit={code}", flush=True)
                if stop.is_set():
                    break
            if prediction_db is not None and time.monotonic() >= next_historical_replay:
                replay_root = directory / ".historical-replay"
                if time.monotonic() >= next_historical_plan:
                    code = _run_offline([
                        "bin.historical_replay_planner",
                        "--archive-directory", str(directory),
                        "--draft-directory", str(replay_root / "drafts"),
                        "--context-db", str(prediction_db.with_name("historical_context.sqlite3")),
                        "--prediction-db", str(prediction_db),
                    ], stop)
                    next_historical_plan = time.monotonic() + 900
                    if code:
                        print(f"[HISTORICAL-PLANNER] status=RETRY exit={code}", flush=True)
                    if stop.is_set():
                        break
                code = _run_offline([
                    "bin.historical_replay_runner",
                    "--request-directory", str(replay_root / "requests"),
                    "--output-directory", str(replay_root / "reports"),
                    "--context-db", str(prediction_db.with_name("historical_context.sqlite3")),
                    "--maximum-new-reports", "36",
                ], stop, timeout_seconds=1_800)
                next_historical_replay = time.monotonic() + 900
                if code:
                    print(f"[HISTORICAL-RUNNER] status=RETRY exit={code}", flush=True)
                if stop.is_set():
                    break
                code = _run_offline([
                    "bin.historical_replay_runner",
                    "--request-directory", str(replay_root / "confirmation-requests"),
                    "--output-directory", str(replay_root / "confirmation-reports"),
                    "--context-db", str(prediction_db.with_name("historical_context.sqlite3")),
                    "--maximum-new-reports", "16",
                    "--import-mode", "automatic_confirmation",
                ], stop, timeout_seconds=1_800)
                if code:
                    print(f"[V23-CONFIRMATION-RUNNER] status=RETRY exit={code}", flush=True)
                if stop.is_set():
                    break
                confirmation_reports = replay_root / "confirmation-reports"
                if any(
                    path.name != "status.json"
                    for path in confirmation_reports.glob("*.json")
                ):
                    from ladder_dragon.strategy.prediction.runtime import (
                        PredictionShadowStore,
                    )
                    from ladder_dragon.strategy.prediction.v23_confirmation import (
                        import_v23_confirmation_directory,
                    )

                    imported = import_v23_confirmation_directory(
                        PredictionShadowStore(prediction_db),
                        confirmation_reports,
                    )
                    atomic_json(
                        replay_root / "confirmation-import-status.json",
                        imported,
                        replace=True,
                    )
            candidate = next((p for p in pending if retry_after.get(p, 0) <= time.monotonic()), None)
            if candidate is None:
                stop.wait(30)
                continue
            started = time.monotonic()
            code = _run_offline(["bin.depth_archive_service", "--calibrate", str(candidate)], stop)
            if code:
                retry_after[candidate] = time.monotonic() + 900
                print(f"[DEPTH-CALIBRATION] status=RETRY exit={code}", flush=True)
            else:
                retry_after.pop(candidate, None)
                elapsed = max(0.001, time.monotonic() - started)
                average_calibration_seconds = (
                    elapsed if average_calibration_seconds is None
                    else average_calibration_seconds * 0.8 + elapsed * 0.2
                )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            # Never publish raw provider bodies, paths, or credentials.
            print(f"[DEPTH-CALIBRATION] status=BLOCKED error={type(exc).__name__}", flush=True)
            stop.wait(30)
