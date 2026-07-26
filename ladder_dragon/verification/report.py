# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect allowlisted evidence and write owner-only harness reports.
"""Sanitized evidence collection and atomic verification report output."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable

from ladder_dragon.execution.execution_latency import load_execution_latencies
from ladder_dragon.execution.order_recovery import read_order_journal_telemetry
from ladder_dragon.strategy.replay_validation import read_replay_validation
from ladder_dragon.verification.models import (
    CheckResult,
    HarnessContext,
    HarnessReport,
    Status,
)
from product_version import __version__


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    index = max(
        0,
        min(
            len(ordered) - 1,
            (percentile * len(ordered) + 99) // 100 - 1,
        ),
    )
    return int(ordered[index])


def _latency_evidence(path: Path | None) -> dict[str, int] | None:
    if path is None or not path.exists():
        return None
    try:
        values = load_execution_latencies(path)
    except (OSError, TypeError, ValueError):
        return None
    if not values:
        return None
    return {
        "samples": len(values),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
    }


def _replay_evidence(path: Path | None) -> dict[str, object]:
    empty = {
        "available": False,
        "ready": False,
        "accuracy": None,
        "errors": {
            "fill_ratio_mae": None,
            "price_bps_mae": None,
            "latency_ms_mae": None,
            "fee_quote_mae": None,
            "slippage_bps_mae": None,
        },
        "covered_orders": 0,
        "reasons": [],
    }
    if path is None or not path.exists():
        return empty
    try:
        report = read_replay_validation(path)
    except (OSError, TypeError, ValueError):
        invalid = dict(empty)
        invalid["reasons"] = ["invalid replay validation evidence"]
        return invalid
    return {
        "available": True,
        "ready": report.ready,
        "accuracy": format(report.fill_classification_accuracy, "f"),
        "errors": {
            "fill_ratio_mae": format(report.fill_ratio_mae, "f"),
            "price_bps_mae": (
                format(report.price_error_bps_mae, "f")
                if report.price_error_bps_mae is not None
                else None
            ),
            "latency_ms_mae": (
                format(report.latency_error_ms_mae, "f")
                if report.latency_error_ms_mae is not None
                else None
            ),
            "fee_quote_mae": (
                format(report.fee_error_quote_mae, "f")
                if report.fee_error_quote_mae is not None
                else None
            ),
            "slippage_bps_mae": (
                format(report.slippage_error_bps_mae, "f")
                if report.slippage_error_bps_mae is not None
                else None
            ),
        },
        "covered_orders": report.covered_orders,
        "reasons": list(report.reasons),
    }


def _unresolved_fills(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        with sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, timeout=2
        ) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "ai_unresolved_fills" not in tables:
                return None
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM ai_unresolved_fills"
                ).fetchone()[0]
            )
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def _test_totals(checks: Iterable[CheckResult]) -> dict[str, int]:
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    for check in checks:
        for name in totals:
            value = check.metrics.get(name)
            if isinstance(value, int) and value >= 0:
                totals[name] += value
    return totals


def _overall_status(checks: tuple[CheckResult, ...]) -> Status:
    required = [check for check in checks if check.required]
    if any(check.status is Status.FAILED for check in required):
        return Status.FAILED
    if any(check.status is Status.BLOCKED for check in required):
        return Status.BLOCKED
    return Status.PASS


def build_report(
    context: HarnessContext,
    checks: tuple[CheckResult, ...],
    commit_sha: str,
) -> HarnessReport:
    options = context.options
    source_paths = list(options.source_paths)
    for optional in (
        options.release_report,
        options.replay_validation,
        options.latency_log,
    ):
        if optional is not None:
            source_paths.append(optional)
    input_hashes: dict[str, str] = {}
    for path in source_paths:
        try:
            input_hashes[str(path)] = sha256_file(path)
        except OSError:
            continue
    journal = read_order_journal_telemetry(options.order_journal)
    lifecycle = journal.get("lifecycle", {}) if journal.get("available") else {}
    exact = {
        "closed": int(lifecycle.get("closed_exact", 0)),
        "tp": int(lifecycle.get("tp", 0)),
        "stop": int(lifecycle.get("stop", 0)),
        "required": int(lifecycle.get("required", 3)),
    }
    status = _overall_status(checks)
    block_reasons = tuple(
        f"{check.name}: {check.summary}"
        for check in checks
        if check.required and check.status is not Status.PASS
    )
    return HarnessReport(
        schema_version=1,
        product_version=__version__,
        commit_sha=commit_sha,
        generated_at=datetime.now(timezone.utc).isoformat(),
        profile=options.profile,
        status=status,
        checks=checks,
        input_hashes=input_hashes,
        tests=_test_totals(checks),
        replay=_replay_evidence(options.replay_validation),
        latency_ms=_latency_evidence(options.latency_log),
        unresolved_fills=_unresolved_fills(options.ai_decisions_db),
        exact_lifecycles=exact,
        block_reasons=block_reasons,
    )


def write_report(path: Path, report: HarnessReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report.as_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
