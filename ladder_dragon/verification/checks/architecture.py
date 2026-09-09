# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: require source ownership verification in local and release profiles.
"""Architecture harness adapter with structured failure evidence."""

import time
import subprocess

from ladder_dragon.verification.architecture.inventory import audit
from ladder_dragon.verification.architecture.references import audit_references
from ladder_dragon.verification.architecture.surfaces import audit_surfaces
from ladder_dragon.verification.architecture.service_links import audit_service_links
from ladder_dragon.verification.models import CheckResult, HarnessContext, Status, EXIT_CODES
from ladder_dragon.verification.architecture.cycle_growth import historical_graph, compare_cycle_growth
from ladder_dragon.verification.checks.release_continuity import check_release_continuity
from ladder_dragon.verification.architecture.cycle_growth import historical_trees
from ladder_dragon.verification.architecture.new_code_sizes import compare_new_code_sizes, compare_legacy_sizes


def check_architecture_new_sizes(context: HarnessContext) -> CheckResult:
    """Require verified lineage before classifying new production code."""
    return _check_sizes(context, "architecture_new_sizes", compare_new_code_sizes)


def check_architecture_legacy_sizes(context: HarnessContext) -> CheckResult:
    """Keep legacy growth enforcement separate from new-code classification."""
    return _check_sizes(context, "architecture_legacy_sizes", compare_legacy_sizes)


def _check_sizes(context: HarnessContext, name: str, compare) -> CheckResult:
    """Share immutable history and fail-closed handling across size checks."""
    started = time.monotonic()
    result = {"status": "BLOCKED", "reason": "verified_size_baseline_unavailable"}
    lineage = check_release_continuity(context)
    if lineage.status is Status.PASS:
        try:
            sha = lineage.metrics["previous_sha"]
            if not isinstance(sha, str):
                raise ValueError("missing prior release")
            current = audit(context.root)
            if current["status"] == "PASS":
                result = compare(historical_trees(context.root, sha), current["sources"])
                result.update(baseline_sha=sha, current_sha=current["commit_sha"], identity_scope=current["identity_scope"])
        except (OSError, UnicodeError, ValueError, SyntaxError, RecursionError, KeyError, subprocess.SubprocessError):
            result = {"status": "BLOCKED", "reason": "verified_size_baseline_unavailable"}
    status = Status(result["status"])
    return CheckResult(name=name, status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Production size check against verified lineage", exit_code=EXIT_CODES[status], metrics=result)


def check_architecture_cycles(context: HarnessContext) -> CheckResult:
    """Use release lineage, never a candidate-supplied budget or graph."""
    started = time.monotonic()
    result = {"status": "BLOCKED", "reason": "verified_cycle_baseline_unavailable"}
    lineage = check_release_continuity(context)
    if lineage.status is Status.PASS:
        try:
            sha = lineage.metrics["previous_sha"]
            if not isinstance(sha, str):
                raise ValueError("missing prior release")
            current = audit(context.root)
            if current["status"] == "PASS":
                previous = historical_graph(context.root, sha)
                result = compare_cycle_growth(previous, current["dependency_graph"])
                result["baseline_sha"] = sha
                result["current_sha"] = current["commit_sha"]
                result["identity_scope"] = current["identity_scope"]
        except (OSError, UnicodeError, ValueError, SyntaxError, RecursionError, KeyError, subprocess.SubprocessError):
            result = {"status": "BLOCKED", "reason": "verified_cycle_baseline_unavailable"}
    status = Status(result["status"])
    return CheckResult(name="architecture_cycles", status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Static cycle growth against verified release lineage",
                       exit_code=EXIT_CODES[status], metrics=result)


def check_architecture(context: HarnessContext) -> CheckResult:
    """Retain the scoped inventory and never suppress a failed source check."""
    started = time.monotonic()
    result = audit(context.root)
    status = Status(result["status"])
    return CheckResult(
        name="architecture_ownership", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Python ownership and static launcher boundary audit",
        exit_code=EXIT_CODES[status], metrics=result,
    )


def check_architecture_references(context: HarnessContext) -> CheckResult:
    """Reject missing source anchors without duplicating financial authority."""
    started = time.monotonic()
    result = audit_references(context.root)
    status = Status(result["status"])
    return CheckResult(
        name="architecture_references", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Reviewed store and existing authority references",
        exit_code=EXIT_CODES[status], metrics=result,
    )


def check_architecture_surfaces(context: HarnessContext) -> CheckResult:
    """Require registered command and deployment source membership."""
    started = time.monotonic()
    result = audit_surfaces(context.root)
    status = Status(result["status"])
    return CheckResult(
        name="architecture_surfaces", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Command and deployment source surface inventory",
        exit_code=EXIT_CODES[status], metrics=result,
    )


def check_architecture_service_links(context: HarnessContext) -> CheckResult:
    """Require the reviewed literal service graph."""
    started = time.monotonic()
    result = audit_service_links(context.root)
    status = Status(result["status"])
    return CheckResult(name="architecture_service_links", status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Literal service and installation source links",
                       exit_code=EXIT_CODES[status], metrics=result)
