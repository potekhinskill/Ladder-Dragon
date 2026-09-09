# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce approved size limits for new production definitions.
"""Existing size debt is reported as out of scope, never approved here."""

import json
from collections import defaultdict

from ladder_dragon.verification.architecture.function_spans import function_spans


def compare_new_code_sizes(previous: dict, sources: list[dict]) -> dict:
    """Classify new paths and lexical names against immutable predecessor source."""
    violations, warnings, ambiguous = [], [], []
    for row in sources:
        path = row["path"]
        if path not in previous and row["lines"] > 500:
            violations.append({"path": path, "reason": "new_module_over_limit", "lines": row["lines"], "limit": 500})
        old, current = defaultdict(list), defaultdict(list)
        for item in function_spans(previous[path]) if path in previous else []:
            old[item["qualified_name"]].append(item["lines"])
        for item in row["functions"]:
            current[item["qualified_name"]].append(item["lines"])
        for name, sizes in sorted(current.items()):
            before = old.get(name, [])
            if len(sizes) > 1 or len(before) > 1:
                # Unchanged ambiguous span groups remain legacy, not new allowances.
                if sorted(sizes) != sorted(before):
                    ambiguous.append({"path": path, "qualified_name": name, "reason": "ambiguous_newness"})
                continue
            if before:
                continue
            item = {"path": path, "qualified_name": name, "lines": sizes[0]}
            if sizes[0] > 120:
                violations.append({**item, "reason": "new_function_over_limit", "limit": 120})
            elif sizes[0] > 80:
                warnings.append({**item, "reason": "new_function_review", "threshold": 80})
    result = {"status": "FAILED" if violations else "BLOCKED" if ambiguous else "PASS",
              "rule": "A06-new-code", "violations": violations, "warnings": warnings, "ambiguous": ambiguous,
              "scope": "New production paths and lexical function names only. Existing size growth, runtime identity, and test size limits are not approved or enforced here."}
    if len(json.dumps(result).encode()) > 2 * 1024 * 1024:
        raise ValueError("size report exceeds ceiling")
    return result


def compare_legacy_sizes(previous: dict, sources: list[dict]) -> dict:
    """Existing definitions cannot exceed the larger of threshold and prior size."""
    violations, ambiguous = [], []
    for row in sources:
        path = row["path"]
        if path not in previous:
            continue
        tree = previous[path]
        prior_lines = getattr(tree, "source_lines", None)
        if type(prior_lines) is not int or prior_lines < 0:
            raise ValueError("missing historical physical size")
        limit = max(500, prior_lines)
        if row["lines"] > limit:
            violations.append({"path": path, "reason": "existing_module_growth", "baseline": prior_lines,
                               "lines": row["lines"], "limit": limit})
        old, current = defaultdict(list), defaultdict(list)
        for item in function_spans(tree):
            old[item["qualified_name"]].append(item["lines"])
        for item in row["functions"]:
            current[item["qualified_name"]].append(item["lines"])
        for name, sizes in sorted(current.items()):
            before = old.get(name, [])
            if not before:
                continue
            if len(sizes) > 1 or len(before) > 1:
                if sorted(sizes) != sorted(before):
                    ambiguous.append({"path": path, "qualified_name": name, "reason": "ambiguous_legacy_identity"})
                continue
            limit = max(120, before[0])
            if sizes[0] > limit:
                violations.append({"path": path, "qualified_name": name, "reason": "existing_function_growth",
                                   "baseline": before[0], "lines": sizes[0], "limit": limit})
    result = {"status": "FAILED" if violations else "BLOCKED" if ambiguous else "PASS",
              "rule": "A06-legacy-growth", "violations": violations, "ambiguous": ambiguous,
              "scope": "Existing production physical sizes only. Non-growth does not approve legacy design or runtime identity; explicit exception review remains separate."}
    if len(json.dumps(result).encode()) > 2 * 1024 * 1024:
        raise ValueError("size report exceeds ceiling")
    return result
