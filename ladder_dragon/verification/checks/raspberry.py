# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify a deployed Raspberry Pi without mutating runtime state.
"""Read-only Raspberry Pi deployment and runtime checks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sqlite3
import subprocess
import time

from ladder_dragon.verification.models import (
    CheckResult,
    CheckSpec,
    HarnessContext,
    Status,
)


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _risk_check(context: HarnessContext) -> CheckResult:
    started = time.monotonic()
    try:
        payload = json.loads(
            context.options.risk_status.read_text(encoding="utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError("risk status is not an object")
        halted = payload.get("halted") is True
        status = Status.BLOCKED if halted else Status.PASS
        summary = (
            "persistent risk state is not halted"
            if status is Status.PASS
            else "persistent risk state is halted"
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        halted = None
        status = Status.BLOCKED
        summary = "persistent risk state is unavailable or invalid"
    return CheckResult(
        name="pi_risk_state",
        status=status,
        required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=summary,
        exit_code=0 if status is Status.PASS else 2,
        metrics={"halted": halted},
    )


def _unresolved_fill_check(context: HarnessContext) -> CheckResult:
    started = time.monotonic()
    count: int | None = None
    try:
        path = context.options.ai_decisions_db
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
                raise ValueError("unresolved fill table is missing")
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM ai_unresolved_fills"
                ).fetchone()[0]
            )
        status = Status.PASS if count == 0 else Status.BLOCKED
        summary = (
            "no unresolved fills"
            if status is Status.PASS
            else "unresolved fills block Pi verification"
        )
    except (OSError, sqlite3.Error, TypeError, ValueError):
        status = Status.BLOCKED
        summary = "unresolved-fill evidence is unavailable"
    return CheckResult(
        name="pi_unresolved_fills",
        status=status,
        required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=summary,
        exit_code=0 if status is Status.PASS else 2,
        metrics={"unresolved_fills": count},
    )


def _runtime_check(context: HarnessContext) -> CheckResult:
    started = time.monotonic()
    path = context.options.runtime_status
    reasons: list[str] = []
    metrics: dict[str, object] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("runtime is not an object")
        state = str(payload.get("state") or "")
        execution_mode = str(payload.get("execution_mode") or "")
        venue = str(payload.get("venue") or "")
        recovery = payload.get("recovery")
        risk = payload.get("risk")
        updated = datetime.fromisoformat(str(payload["updated_at"]))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        heartbeat_age = max(
            0, int(datetime.now(timezone.utc).timestamp() - updated.timestamp())
        )
        metrics.update(
            {
                "state": state,
                "execution_mode": execution_mode,
                "venue": venue,
                "heartbeat_age_sec": heartbeat_age,
            }
        )
        if state != "RUNNING":
            reasons.append("runtime is not RUNNING")
        if heartbeat_age > 90:
            reasons.append("runtime heartbeat is stale")
        if not isinstance(recovery, dict) or recovery.get("blocked") is not False:
            reasons.append("authenticated recovery evidence is incomplete")
        if not isinstance(risk, dict):
            reasons.append("risk snapshot is unavailable")
        else:
            if risk.get("halted") is True or risk.get("buy_blocked") is True:
                reasons.append("risk currently blocks trading")
            delta = risk.get("reconciliation_delta")
            if delta not in (None, [], {}):
                reasons.append("account and journal reconciliation differs")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        reasons.append("runtime status is unavailable or invalid")
    status = Status.PASS if not reasons else Status.BLOCKED
    return CheckResult(
        name="pi_runtime_reconciliation",
        status=status,
        required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=(
            "fresh authenticated runtime and reconciliation evidence"
            if status is Status.PASS
            else "; ".join(reasons)
        ),
        metrics=metrics,
    )


def _deployed_sha_check(context: HarnessContext) -> CheckResult:
    started = time.monotonic()
    expected = (context.options.expected_sha or "").lower()
    github_sha = (context.options.github_sha or "").lower()
    release_verified = False
    upstream = None
    if not FULL_SHA.fullmatch(expected) or not FULL_SHA.fullmatch(
        github_sha
    ):
        status = Status.BLOCKED
        summary = (
            "Pi profile requires --expected-sha and --github-sha "
            "with 40 hexadecimal characters"
        )
        actual = None
    else:
        try:
            report_path = context.options.release_report
            if report_path is None:
                raise ValueError("release report is missing")
            release = json.loads(report_path.read_text(encoding="utf-8"))
            release_verified = (
                isinstance(release, dict)
                and release.get("schema_version") == 1
                and release.get("profile") == "release"
                and release.get("status") == "PASS"
                and str(release.get("commit_sha") or "").lower() == expected
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            release_verified = False
        try:
            actual = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=context.root,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip().lower()
            upstream = subprocess.run(
                ["git", "rev-parse", "@{upstream}"],
                cwd=context.root,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip().lower()
        except (OSError, subprocess.SubprocessError):
            actual = None
            upstream = None
        if not release_verified:
            status = Status.BLOCKED
            summary = "a PASS release artifact for the expected SHA is required"
        elif github_sha != expected:
            status = Status.BLOCKED
            summary = "release SHA differs from the reviewed GitHub SHA"
        elif upstream != github_sha:
            status = Status.BLOCKED
            summary = "local GitHub tracking SHA differs from the reviewed SHA"
        else:
            status = Status.PASS if actual == expected else Status.BLOCKED
            summary = (
                "deployed commit matches the tested release SHA"
                if status is Status.PASS
                else "deployed commit does not match the tested release SHA"
            )
    return CheckResult(
        name="pi_deployed_sha",
        status=status,
        required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=summary,
        metrics={
            "matched": status is Status.PASS,
            "release_artifact_verified": release_verified,
            "github_sha_matched": (
                github_sha == expected == upstream
            ),
        },
    )


def raspberry_checks(context: HarnessContext) -> list[CheckSpec]:
    python = context.python
    options = context.options
    return [
        CheckSpec(name="pi_deployed_sha", check=_deployed_sha_check),
        CheckSpec(
            name="pi_mybot_service",
            argv=("systemctl", "is-active", "--quiet", "mybot"),
            timeout_sec=30,
        ),
        CheckSpec(
            name="pi_health_service",
            argv=("systemctl", "is-active", "--quiet", "pi-healthd"),
            timeout_sec=30,
        ),
        CheckSpec(name="pi_risk_state", check=_risk_check),
        CheckSpec(name="pi_runtime_reconciliation", check=_runtime_check),
        CheckSpec(
            name="pi_unresolved_fills",
            check=_unresolved_fill_check,
        ),
        CheckSpec(
            name="pi_user_stream_soak",
            argv=(
                python,
                "-m",
                "bin.audit_user_stream_soak",
                str(options.user_stream_status),
                "--minimum-hours",
                "24",
            ),
            timeout_sec=120,
        ),
        CheckSpec(
            name="pi_production_soak",
            argv=(
                python,
                "-m",
                "bin.production_soak_report",
                "--runtime",
                str(options.runtime_status),
                "--journal",
                str(options.order_journal),
                "--prediction",
                str(options.prediction_db),
            ),
            timeout_sec=120,
        ),
    ]
