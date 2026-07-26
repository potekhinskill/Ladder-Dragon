# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define deterministic local verification checks.
"""Local source, test, numeric and secret checks."""

from __future__ import annotations

from ladder_dragon.verification.models import CheckSpec, HarnessContext


def local_checks(context: HarnessContext) -> list[CheckSpec]:
    python = context.python
    return [
        CheckSpec(
            name="source_compile",
            argv=(python, "-m", "compileall", "-q", "."),
            timeout_sec=300,
        ),
        CheckSpec(
            name="pytest",
            argv=(python, "-m", "pytest"),
            timeout_sec=1800,
        ),
        CheckSpec(
            name="numeric_boundary_audit",
            argv=(python, "-m", "bin.audit_numeric_boundaries"),
            timeout_sec=120,
        ),
        CheckSpec(
            name="tracked_secret_scan",
            argv=(python, "deploy/scan_tracked_secrets.py"),
            timeout_sec=120,
        ),
    ]
