# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose the read-only architecture inventory command.
"""Print bounded, source-only architecture evidence."""

import json
from pathlib import Path

from ladder_dragon.verification.architecture.inventory import audit, MAX_REPORT
from ladder_dragon.verification.architecture.references import audit_references
from ladder_dragon.verification.architecture.surfaces import audit_surfaces
from ladder_dragon.verification.architecture.service_links import audit_service_links
from ladder_dragon.verification.models import EXIT_CODES, Status


def main() -> int:
    """Audit the checkout without importing its runtime entry points."""
    root = Path(__file__).resolve().parents[3]
    result = audit(root)
    result["reference_map"] = audit_references(root)
    result["surfaces"] = audit_surfaces(root)
    result["service_links"] = audit_service_links(root)
    statuses = {result["status"], *(result[key]["status"] for key in ("reference_map", "surfaces", "service_links"))}
    result["status"] = "FAILED" if "FAILED" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASS"
    if len(json.dumps(result).encode()) > MAX_REPORT:
        result = {"status": "BLOCKED", "reason": "architecture_report_exceeds_ceiling"}
    print(json.dumps(result, sort_keys=True))
    return EXIT_CODES[Status(result["status"])]
