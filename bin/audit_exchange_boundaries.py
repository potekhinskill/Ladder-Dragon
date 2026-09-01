#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: restrict authenticated exchange transport to reviewed boundary adapters.
"""AST audit for direct authenticated exchange transport calls."""

from __future__ import annotations

import ast
import json
from pathlib import Path


APPROVED_METHODS = {
    "ladder_dragon/execution/binance_transport.py": frozenset({"*"}),
    "ladder_dragon/execution/orders/runtime.py": frozenset({"GET", "POST", "DELETE"}),
    "ladder_dragon/execution/executor_recovery.py": frozenset({"GET", "DELETE"}),
    "ladder_dragon/execution/cancel_replace.py": frozenset({"POST"}),
    "ladder_dragon/execution/worker/safety_cancel.py": frozenset({"DELETE"}),
    "ladder_dragon/execution/worker/lifecycle.py": frozenset({"GET"}),
    "ladder_dragon/execution/worker/runtime.py": frozenset({"*"}),
    "ladder_dragon/execution/executor_market.py": frozenset({"GET"}),
    "ladder_dragon/execution/executor_stats.py": frozenset({"GET"}),
}
TRANSPORT_NAMES = frozenset({"signed_request", "_signed_request"})


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _method(node: ast.Call) -> str:
    if node.args and isinstance(node.args[0], ast.Constant):
        value = node.args[0].value
        if isinstance(value, str):
            return value.upper()
    return "DYNAMIC"


def audit_exchange_boundaries(root: Path) -> dict[str, object]:
    violations: list[str] = []
    observed: list[dict[str, object]] = []
    for path in sorted((root / "ladder_dragon" / "execution").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        allowed = APPROVED_METHODS.get(relative, frozenset())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in TRANSPORT_NAMES:
                continue
            method = _method(node)
            observed.append({"path": relative, "line": node.lineno, "method": method})
            if "*" not in allowed and method not in allowed:
                violations.append(
                    f"{relative}:{node.lineno}:unapproved {method} authenticated transport"
                )
    return {
        "ready": not violations,
        "observed": observed,
        "violations": sorted(violations),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit_exchange_boundaries(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
