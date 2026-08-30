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
from ladder_dragon.strategy.volatility_policy import read_volatility_policy


VOLATILITY_CONFIRMATION_SPAN_MS = 2 * 86_400_000


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
    policy = read_volatility_policy(path)
    cutoff = int(policy["cutoff_ts_ms"])
    selection = set(policy["selection_archive_sha256s"])
    confirmation = [
        row for row in rows
        if row.first_ts_ms > cutoff
        and row.archive_sha256 not in selection
        and row.eligible
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
    ready = bool(
        span >= VOLATILITY_CONFIRMATION_SPAN_MS
        and all(counts[name] > 0 for name in counts)
    )
    return {
        "status": "PASS" if ready else "COLLECTING_DISJOINT_CONFIRMATION",
        "policy_sha256": policy["policy_sha256"],
        "selection_cutoff_ts_ms": cutoff,
        "confirmation_report_count": len(confirmation),
        "confirmation_span_ms": span,
        "required_confirmation_span_ms": VOLATILITY_CONFIRMATION_SPAN_MS,
        "confirmation_bucket_counts": counts,
        "selection_sources_reused": False,
    }


def calibration_inventory(directory: Path) -> tuple[dict, list[Path]]:
    """Distinguish missing reports from genuinely absent volatility regimes."""
    missing: list[Path] = []
    regimes: Counter = Counter()
    archived = reports = invalid = ineligible = 0
    sidecars = []
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
            if not report_path.exists():
                missing.append(archive)
                continue
            payload = bounded_json(report_path)
            if type(payload.get("eligible")) is not bool:
                raise ValueError("calibration eligibility must be boolean")
            report = ReplayCalibration.from_dict(payload)
            if report.archive_sha256 != metadata["archive_sha256"]:
                raise ValueError("calibration source mismatch")
            reports += 1
            if report.eligible:
                eligible_rows.append(report)
                regimes[volatility_regime(report.volatility_bps_p95)] += 1
            else:
                ineligible += 1
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
            invalid += 1
    absent = [name for name in ("low", "normal", "high") if not regimes[name]]
    return {
        "schema_version": 1, "mode": "SHADOW", "apply_allowed": False,
        "status": "INCOMPLETE" if missing or invalid or absent else "REGIMES_COVERED",
        "archives": archived, "calibration_reports": reports,
        "missing_calibrations": len(missing), "invalid_artifacts": invalid,
        "ineligible_calibrations": ineligible, "eligible_regime_counts": dict(regimes),
        "missing_volatility_regimes": absent,
        "high_coverage_conclusion": (
            "BACKLOG_NOT_CALIBRATED" if not regimes["high"] and missing
            else "NOT_OBSERVED" if not regimes["high"] else "OBSERVED"
        ),
        "order_validation_proven": False,
        "frozen_volatility_policy": _frozen_volatility_status(
            directory, eligible_rows
        ),
    }, missing


def calibrate_segment(archive: Path) -> None:
    """Produce one immutable report, without touching prediction evidence."""
    segments = verified_segments([archive])
    policy = PRODUCTION_REPLAY_ACCEPTANCE_POLICY
    report = calibrate_market_events(
        iter_segment_events(segments, exchange_clock=True),
        source_sha256=segments[0][1]["archive_sha256"],
        min_book_events=policy.minimum_book_events, min_trades=policy.minimum_trades,
    )
    atomic_json(archive.with_suffix(".calibration.json"), report.as_dict())


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
    while not stop.is_set():
        try:
            status, pending = calibration_inventory(directory)
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
                ], stop, timeout_seconds=1_800)
                if code:
                    print(f"[V23-CONFIRMATION-RUNNER] status=RETRY exit={code}", flush=True)
                if stop.is_set():
                    break
            candidate = next((p for p in pending if retry_after.get(p, 0) <= time.monotonic()), None)
            if candidate is None:
                stop.wait(30)
                continue
            code = _run_offline(["bin.depth_archive_service", "--calibrate", str(candidate)], stop)
            if code:
                retry_after[candidate] = time.monotonic() + 900
                print(f"[DEPTH-CALIBRATION] status=RETRY exit={code}", flush=True)
            else:
                retry_after.pop(candidate, None)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            # Never publish raw provider bodies, paths, or credentials.
            print(f"[DEPTH-CALIBRATION] status=BLOCKED error={type(exc).__name__}", flush=True)
            stop.wait(30)
