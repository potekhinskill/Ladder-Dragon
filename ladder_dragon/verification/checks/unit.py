# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define deterministic local verification checks.
"""Local source, test, numeric and secret checks."""

from __future__ import annotations

from ladder_dragon.verification.checks.release_continuity import (
    release_continuity_checks,
)
from ladder_dragon.verification.models import CheckSpec, HarnessContext


def local_checks(context: HarnessContext) -> list[CheckSpec]:
    python = context.python
    return release_continuity_checks(context) + [
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
            name="semantic_authority_audit",
            argv=(python, "-m", "bin.audit_semantic_authorities"),
            timeout_sec=120,
        ),
        CheckSpec(
            name="exchange_boundary_audit",
            argv=(python, "-m", "bin.audit_exchange_boundaries"),
            timeout_sec=120,
        ),
        CheckSpec(
            name="guard_contract_audit",
            argv=(python, "-m", "bin.audit_guard_contracts"),
            timeout_sec=120,
        ),
        CheckSpec(
            name="tracked_secret_scan",
            argv=(python, "deploy/scan_tracked_secrets.py"),
            timeout_sec=120,
        ),
        CheckSpec(
            name="semgrep_rule_tests",
            argv=(python, "-m", "bin.semgrep_scan", "--rules-test"),
            timeout_sec=300,
        ),
        CheckSpec(
            name="semgrep_static_analysis",
            argv=(python, "-m", "bin.semgrep_scan"),
            timeout_sec=900,
        ),
    ]
