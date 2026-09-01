#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reject copied financial vocabularies and ambiguous indicator implementations.
"""AST audit for domain-owned financial semantic authorities."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from ladder_dragon.execution.trade_accounting import (
    DEFAULT_SPOT_FEE_PCT,
    KNOWN_QUOTE_ASSETS,
    VALUED_COMMISSION_STATUSES,
)
from ladder_dragon.strategy.fee_defaults import (
    DEFAULT_RESEARCH_MAKER_FEE_PCT,
    DEFAULT_RESEARCH_TAKER_FEE_PCT,
)

QUOTE_ASSETS = frozenset(KNOWN_QUOTE_ASSETS)
COMMISSION_STATUSES = VALUED_COMMISSION_STATUSES
DEFAULT_FEE_LITERALS = frozenset(
    {
        format(DEFAULT_SPOT_FEE_PCT, "f"),
        format(DEFAULT_RESEARCH_MAKER_FEE_PCT, "f"),
        format(DEFAULT_RESEARCH_TAKER_FEE_PCT, "f"),
    }
)
COLLECTION_AUTHORITIES = frozenset(
    {
        "ladder_dragon/execution/trade_accounting.py",
        "ladder_dragon/risk/asset_policy.py",
    }
)
FEE_LITERAL_AUTHORITIES = frozenset(
    {
        "ladder_dragon/execution/trade_accounting.py",
        "ladder_dragon/strategy/fee_defaults.py",
    }
)
INDICATOR_AUTHORITY = "ladder_dragon/strategy/indicators.py"
ATR_CONSUMER_NAMES = frozenset(
    {
        "_atr_pct",
        "atr_from_klines",
        "atr_pct_from_klines",
        "calc_atr",
        "compute_atr",
        "estimate_atr_ratio",
    }
)
CANONICAL_ATR_CALLS = frozenset(
    {
        "atr_ema_from_klines",
        "atr_sma_from_klines",
        "atr_wilder_from_klines",
    }
)


def _string_collection(node: ast.AST) -> frozenset[str]:
    if not isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return frozenset()
    values = {
        item.value
        for item in node.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }
    return frozenset(values)


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id.lower()
    if isinstance(node, ast.Attribute):
        return node.attr.lower()
    return ""


def _decimal_literal(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    name = _target_name(node.func)
    value = node.args[0]
    if name not in {"decimal", "d"} or not isinstance(value, ast.Constant):
        return None
    return str(value.value)


def _fee_literal_violations(tree: ast.AST, relative: str) -> list[str]:
    if relative in FEE_LITERAL_AUTHORITIES:
        return []
    violations: list[str] = []
    for node in ast.walk(tree):
        pairs: list[tuple[str, ast.AST]] = []
        if isinstance(node, ast.Assign):
            pairs.extend((_target_name(target), node.value) for target in node.targets)
        elif isinstance(node, ast.AnnAssign):
            pairs.append((_target_name(node.target), node.value))
        elif isinstance(node, ast.keyword) and node.arg:
            pairs.append((node.arg.lower(), node.value))
        for name, value in pairs:
            literal = _decimal_literal(value)
            if "fee" in name and literal in DEFAULT_FEE_LITERALS:
                violations.append(f"{relative}:{node.lineno}:copied fee default")
    return violations


def _calls_canonical_atr(function: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and _target_name(node.func) in CANONICAL_ATR_CALLS
        for node in ast.walk(function)
    )


def audit_semantic_authorities(root: Path) -> dict[str, object]:
    violations: list[str] = []
    sources = sorted((root / "ladder_dragon").rglob("*.py"))
    sources.extend(sorted((root / "bin").glob("*.py")))
    for path in sources:
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            values = _string_collection(node)
            if relative not in COLLECTION_AUTHORITIES:
                if len(values & QUOTE_ASSETS) >= 4:
                    violations.append(
                        f"{relative}:{node.lineno}:copied quote vocabulary"
                    )
                if len(values & COMMISSION_STATUSES) >= 3:
                    violations.append(
                        f"{relative}:{node.lineno}:copied commission vocabulary"
                    )
            if relative != INDICATOR_AUTHORITY and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                name = node.name.lower()
                if name in CANONICAL_ATR_CALLS:
                    violations.append(
                        f"{relative}:{node.lineno}:duplicate named ATR authority"
                    )
                if name in ATR_CONSUMER_NAMES and not _calls_canonical_atr(node):
                    violations.append(
                        f"{relative}:{node.lineno}:ATR consumer bypasses authority"
                    )
        violations.extend(_fee_literal_violations(tree, relative))
    return {"ready": not violations, "violations": sorted(set(violations))}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit_semantic_authorities(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
