#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: ensure registered fail-closed guards contain executable rejection paths.
"""AST audit for critical functions that promise mandatory validation."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from ladder_dragon.verification.source_contracts import qualified_functions


CRITICAL_GUARDS = {
    "ladder_dragon/execution/time_safety.py": (
        "ClockCheck.require_safe",
    ),
    "ladder_dragon/supervision/execution_promotion.py": (
        "require_safe_execution_scope",
        "require_promotion_report_integrity",
    ),
    "ladder_dragon/strategy/prediction/episode_semantics.py": (
        "require_execution_regime_contract",
        "require_historical_regime_contract",
        "require_runtime_regime_contract",
    ),
    "ladder_dragon/execution/worker/champion_preflight.py": (
        "require_live_champion",
    ),
    "ladder_dragon/execution/worker/exchange_safety.py": (
        "require_order_status",
    ),
    "ladder_dragon/verification/live/mainnet_canary.py": (
        "require_confirmations",
        "require_services_stopped",
        "require_release_not_already_passed",
    ),
}


def audit_guard_contracts(root: Path) -> dict[str, object]:
    violations: list[str] = []
    checked: list[str] = []
    for relative, names in CRITICAL_GUARDS.items():
        path = root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        functions = qualified_functions(tree)
        for name in names:
            identity = f"{relative}:{name}"
            checked.append(identity)
            function = functions.get(name)
            if function is None:
                violations.append(identity + ":missing")
                continue
            descendants = tuple(ast.walk(function))
            if not any(isinstance(node, ast.Raise) for node in descendants):
                violations.append(identity + ":no rejection path")
            if not any(
                isinstance(node, (ast.If, ast.Try)) for node in descendants
            ):
                violations.append(identity + ":no validation branch")
    return {
        "ready": not violations,
        "checked": checked,
        "violations": sorted(violations),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit_guard_contracts(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
