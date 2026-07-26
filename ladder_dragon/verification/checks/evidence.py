# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate optional external evidence before it enters a report.
"""Fail-closed validation for source, replay and latency evidence."""

from __future__ import annotations

import time

from ladder_dragon.execution.execution_latency import load_execution_latencies
from ladder_dragon.strategy.replay_validation import read_replay_validation
from ladder_dragon.verification.models import (
    CheckResult,
    CheckSpec,
    HarnessContext,
    Status,
)


def _check_evidence(context: HarnessContext) -> CheckResult:
    started = time.monotonic()
    options = context.options
    reasons: list[str] = []
    metrics: dict[str, object] = {}
    for path in options.source_paths:
        if not path.is_file():
            reasons.append("a requested source artifact is unavailable")
            break
    if options.release_report is not None and not options.release_report.is_file():
        reasons.append("the requested release report is unavailable")
    if options.replay_validation is not None:
        try:
            replay = read_replay_validation(options.replay_validation)
            metrics["replay_ready"] = replay.ready
            metrics["replay_covered_orders"] = replay.covered_orders
            if not replay.ready:
                reasons.append("replay validation is not ready")
        except (OSError, TypeError, ValueError):
            reasons.append("replay validation is invalid")
    if options.latency_log is not None:
        try:
            latency = load_execution_latencies(options.latency_log)
            metrics["latency_samples"] = len(latency)
            if not latency:
                reasons.append("execution latency evidence has no NEW samples")
        except (OSError, TypeError, ValueError):
            reasons.append("execution latency evidence is invalid")
    status = Status.PASS if not reasons else Status.BLOCKED
    return CheckResult(
        name="evidence_integrity",
        status=status,
        required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=(
            "requested evidence is valid"
            if status is Status.PASS
            else "; ".join(reasons)
        ),
        exit_code=0 if status is Status.PASS else 2,
        metrics=metrics,
    )


def evidence_checks(context: HarnessContext) -> list[CheckSpec]:
    return [CheckSpec(name="evidence_integrity", check=_check_evidence)]
