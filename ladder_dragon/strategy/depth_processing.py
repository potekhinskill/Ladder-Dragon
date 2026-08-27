# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: process finalized public segments outside the recording process.
"""Bounded calibration backlog and truthful public-context coverage status."""

from __future__ import annotations

from collections import Counter
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


def calibration_inventory(directory: Path) -> tuple[dict, list[Path]]:
    """Distinguish missing reports from genuinely absent volatility regimes."""
    missing: list[Path] = []
    regimes: Counter = Counter()
    archived = reports = invalid = ineligible = 0
    sidecars = []
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


def _run_offline(arguments: list[str], stop) -> int:
    with subprocess.Popen([sys.executable, "-m", *arguments],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
        deadline = time.monotonic() + 300
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
