# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: execute verification checks without leaking child-process output.
"""Fail-closed subprocess runner for the unified verification harness."""

from __future__ import annotations

import re
import subprocess
import time

from ladder_dragon.verification.models import (
    CheckResult,
    CheckSpec,
    HarnessContext,
    Status,
)
from ladder_dragon.verification.profiles import checks_for_profile


_PYTEST_TOTAL = {
    "passed": re.compile(r"(?<!\d)(\d+) passed\b"),
    "failed": re.compile(r"(?<!\d)(\d+) failed\b"),
    "skipped": re.compile(r"(?<!\d)(\d+) skipped\b"),
}


def _safe_metrics(output: str) -> dict[str, object]:
    metrics: dict[str, object] = {}
    for name, pattern in _PYTEST_TOTAL.items():
        matches = pattern.findall(output)
        if matches:
            metrics[name] = int(matches[-1])
    return metrics


class HarnessRunner:
    def __init__(self, context: HarnessContext) -> None:
        self.context = context

    def _run_spec(self, spec: CheckSpec) -> CheckResult:
        started = time.monotonic()
        if spec.blocked_reason is not None:
            return CheckResult(
                name=spec.name,
                status=Status.BLOCKED,
                required=spec.required,
                duration_ms=0,
                summary=spec.blocked_reason,
                exit_code=2,
            )
        if spec.check is not None:
            try:
                result = spec.check(self.context)
            except (
                OSError,
                TypeError,
                ValueError,
                subprocess.SubprocessError,
            ):
                return CheckResult(
                    name=spec.name,
                    status=Status.FAILED,
                    required=spec.required,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    summary="internal verification check failed",
                    exit_code=1,
                )
            if result.name != spec.name:
                return CheckResult(
                    name=spec.name,
                    status=Status.FAILED,
                    required=spec.required,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    summary="verification check returned an unexpected identity",
                    exit_code=1,
                )
            return result
        if not spec.argv:
            return CheckResult(
                name=spec.name,
                status=Status.BLOCKED,
                required=spec.required,
                duration_ms=0,
                summary="mandatory check has no implementation",
                exit_code=2,
            )
        try:
            completed = subprocess.run(
                list(spec.argv),
                cwd=self.context.root,
                capture_output=True,
                text=True,
                timeout=spec.timeout_sec,
                check=False,
            )
        except FileNotFoundError:
            return CheckResult(
                name=spec.name,
                status=Status.BLOCKED,
                required=spec.required,
                duration_ms=int((time.monotonic() - started) * 1000),
                summary="required verification executable is unavailable",
                exit_code=2,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                name=spec.name,
                status=Status.FAILED,
                required=spec.required,
                duration_ms=int((time.monotonic() - started) * 1000),
                summary="verification check exceeded its time limit",
                exit_code=1,
            )
        except OSError:
            return CheckResult(
                name=spec.name,
                status=Status.FAILED,
                required=spec.required,
                duration_ms=int((time.monotonic() - started) * 1000),
                summary="verification process could not be started",
                exit_code=1,
            )
        if completed.returncode == 0:
            status = Status.PASS
            summary = "check passed"
        elif completed.returncode == 2:
            status = Status.BLOCKED
            summary = "check reported an unmet safety gate"
        else:
            status = Status.FAILED
            summary = "check failed"
        # Child output is parsed only for allowlisted counters and is never
        # persisted. This prevents signed URLs or credentials from entering
        # the report even when a child command fails noisily.
        output = f"{completed.stdout}\n{completed.stderr}"
        return CheckResult(
            name=spec.name,
            status=status,
            required=spec.required,
            duration_ms=int((time.monotonic() - started) * 1000),
            summary=summary,
            exit_code=int(completed.returncode),
            metrics=_safe_metrics(output),
        )

    def run(self) -> tuple[CheckResult, ...]:
        return tuple(
            self._run_spec(spec) for spec in checks_for_profile(self.context)
        )
