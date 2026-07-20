#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: prevent float conversion from returning to exact execution modules.
"""AST audit for direct float calls at financial module boundaries."""

from __future__ import annotations

import ast
import json
from pathlib import Path


LIMITS = {
    "bin/ai_supervisor.py": 0,
    "bin/autosize_universal.py": 0,
    "ladder_dragon/ai/ai_context.py": 0,
    "ladder_dragon/numeric_compat.py": 1,
    "ladder_dragon/execution/executor_orders.py": 0,
    "ladder_dragon/execution/executor_protection.py": 0,
}


def direct_float_calls(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
        for node in ast.walk(tree)
    )


def audit_numeric_boundaries(root: Path) -> dict[str, object]:
    counts = {
        name: direct_float_calls(root / name) for name in LIMITS
    }
    regressions = {
        name: {"actual": counts[name], "maximum": maximum}
        for name, maximum in LIMITS.items()
        if counts[name] > maximum
    }
    return {
        "ready": not regressions,
        "counts": counts,
        "maximums": dict(LIMITS),
        "regressions": regressions,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit_numeric_boundaries(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
