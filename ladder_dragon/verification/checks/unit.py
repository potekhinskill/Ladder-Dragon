# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define deterministic local verification checks.
"""Local source, test, numeric and secret checks."""

from __future__ import annotations

from ladder_dragon.verification.checks.release_continuity import (
    release_continuity_checks,
)
from ladder_dragon.verification.models import CheckSpec, HarnessContext
from ladder_dragon.verification.checks.architecture import (
    check_architecture, check_architecture_references, check_architecture_surfaces, check_architecture_service_links,
    check_architecture_cycles, check_architecture_new_sizes, check_architecture_legacy_sizes,
)


def local_checks(context: HarnessContext) -> list[CheckSpec]:
    """Keep comprehensive checks at completion; focused iteration uses pytest directly."""
    python = context.python
    return release_continuity_checks(context) + [
        CheckSpec(name="architecture_ownership", check=check_architecture),
        CheckSpec(name="architecture_cycles", check=check_architecture_cycles),
        CheckSpec(name="architecture_new_sizes", check=check_architecture_new_sizes),
        CheckSpec(name="architecture_legacy_sizes", check=check_architecture_legacy_sizes),
        CheckSpec(name="architecture_references", check=check_architecture_references),
        CheckSpec(name="architecture_surfaces", check=check_architecture_surfaces),
        CheckSpec(name="architecture_service_links", check=check_architecture_service_links),
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
            name="execution_authority_path_audit",
            argv=(python, "-m", "bin.audit_execution_authority_paths"),
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
