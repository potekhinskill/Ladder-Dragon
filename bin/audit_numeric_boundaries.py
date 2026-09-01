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
    "ladder_dragon/risk/risk_manager.py": 6,
    "ladder_dragon/supervision/risk_cycle.py": 0,
    "ladder_dragon/supervision/runtime.py": 0,
    "ladder_dragon/execution/worker/runtime.py": 0,
    "ladder_dragon/ai/context/runtime.py": 0,
    "ladder_dragon/numeric_compat.py": 1,
    "ladder_dragon/execution/cost_basis_import.py": 3,
    "ladder_dragon/execution/commission_revaluation.py": 1,
    "ladder_dragon/execution/trade_accounting.py": 0,
    "ladder_dragon/execution/inventory_lots.py": 0,
    "ladder_dragon/execution/orders/runtime.py": 0,
    "ladder_dragon/execution/protection/runtime.py": 0,
    "ladder_dragon/execution/protection/breakeven.py": 0,
}
EXACT_PACKAGE_ROOTS = (
    "ladder_dragon/execution/orders",
    "ladder_dragon/execution/protection",
)


def audited_limits(root: Path) -> dict[str, int]:
    """Add every exact-execution module to the zero-float budget."""
    limits = dict(LIMITS)
    for relative_root in EXACT_PACKAGE_ROOTS:
        package = root / relative_root
        if not package.exists():
            continue
        for path in package.rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            limits.setdefault(relative, 0)
    return limits


def direct_float_calls(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
        for node in ast.walk(tree)
    )


def audit_numeric_boundaries(root: Path) -> dict[str, object]:
    limits = audited_limits(root)
    counts = {
        name: direct_float_calls(root / name) for name in limits
    }
    regressions = {
        name: {"actual": counts[name], "maximum": maximum}
        for name, maximum in limits.items()
        if counts[name] > maximum
    }
    return {
        "ready": not regressions,
        "counts": counts,
        "maximums": limits,
        "regressions": regressions,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit_numeric_boundaries(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
