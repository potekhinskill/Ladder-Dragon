#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: process pinned historical replay requests without importing selection.
"""Create immutable SHADOW reports from a bounded operator request queue."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from bin.replay_historical_entries import run_replay_request_batch
from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json
from ladder_dragon.strategy.prediction.historical_policy import fingerprint

MAXIMUM_REQUESTS = 256


def _identity(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("historical replay request is oversized")
    return hashlib.sha256(raw).hexdigest()


def process_requests(
    request_directory: Path,
    output_directory: Path,
    context_db: Path,
    *,
    maximum_new_reports: int = 36,
    import_mode: str = "manual_selection",
) -> dict[str, object]:
    """Process one same-block policy batch under an explicit import contract."""
    if not 1 <= maximum_new_reports <= 64:
        raise ValueError("historical replay work limit is invalid")
    if import_mode not in {"manual_selection", "automatic_confirmation"}:
        raise ValueError("historical replay import mode is invalid")
    request_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    requests = sorted(request_directory.glob("*.json"))
    if len(requests) > MAXIMUM_REQUESTS:
        raise ValueError("historical replay request capacity reached")
    completed = failed = created = 0
    pending: dict[str, list[tuple[Path, Path]]] = {}
    for request in requests:
        try:
            identity = _identity(request)
            output = output_directory / f"{identity}.json"
            if output.exists():
                raw = output.read_bytes()
                if len(raw) > 16 * 1024 * 1024:
                    raise ValueError("historical replay report is oversized")
                report = json.loads(raw)
                if not isinstance(report, dict):
                    raise ValueError("historical replay report must be an object")
                embedded = str(report.get("report_sha256", ""))
                body = {
                    key: value
                    for key, value in report.items()
                    if key != "report_sha256"
                }
                if embedded != fingerprint(body):
                    raise ValueError("historical replay report identity differs")
                if report.get("status") != "COMPLETE_SELECTION_REPLAY":
                    raise ValueError("historical replay report is incomplete")
                completed += 1
                continue
            payload = bounded_json(request)
            group_fields = (
                (
                    "request_schema_version", "cohort_contract",
                    "stability_block_index", "paths",
                )
                if payload.get("request_schema_version") == 2
                else (
                    "archives", "start_ms", "entry_end_ms", "end_ms",
                    "cutoff_ms",
                )
            )
            group = fingerprint({
                key: payload.get(key) for key in group_fields
            })
            pending.setdefault(group, []).append((request, output))
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError, sqlite3.Error):
            failed += 1
    for group in pending.values():
        if created >= maximum_new_reports:
            break
        work = group[: maximum_new_reports - created]
        try:
            reports = run_replay_request_batch(work, context_db=context_db)
            if any(
                report.get("status") != "COMPLETE_SELECTION_REPLAY"
                for report in reports
            ):
                raise ValueError("historical replay report is incomplete")
            created += len(reports)
            completed += len(reports)
        except (
            OSError, RuntimeError, ValueError, KeyError, TypeError,
            ArithmeticError, sqlite3.Error,
        ):
            failed += len(work)
    automatic_confirmation = import_mode == "automatic_confirmation"
    ready = completed >= (1 if automatic_confirmation else 3)
    status = {
        "schema_version": 1,
        "mode": "SHADOW",
        "apply_allowed": False,
        "import_mode": import_mode,
        "selection_import_automatic": False,
        "confirmation_import_automatic": automatic_confirmation,
        "request_count": len(requests),
        "completed_report_count": completed,
        "failed_request_count": failed,
        "new_report_count": created,
        "operator_review_ready": (
            failed == 0 and ready and not automatic_confirmation
        ),
        "status": (
            "BLOCKED" if failed
            else "WAITING_REQUESTS" if not requests
            else "READY_FOR_AUTOMATIC_IMPORT"
            if ready and automatic_confirmation
            else "READY_FOR_OPERATOR_REVIEW" if ready
            else "COLLECTING_REPORTS"
        ),
    }
    atomic_json(output_directory / "status.json", status, replace=True)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-directory", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--context-db", required=True, type=Path)
    parser.add_argument("--maximum-new-reports", type=int, default=36)
    parser.add_argument(
        "--import-mode",
        choices=("manual_selection", "automatic_confirmation"),
        default="manual_selection",
    )
    args = parser.parse_args()
    try:
        report = process_requests(
            args.request_directory,
            args.output_directory,
            args.context_db,
            maximum_new_reports=args.maximum_new_reports,
            import_mode=args.import_mode,
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
        sqlite3.Error,
    ) as exc:
        print(f"[HISTORICAL-RUNNER] status=BLOCKED error={type(exc).__name__}")
        return 2
    print(
        f"[HISTORICAL-RUNNER] status={report['status']} "
        f"completed={report['completed_report_count']}"
    )
    return 2 if report["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
