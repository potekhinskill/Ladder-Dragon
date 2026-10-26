# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce public ticker validation ownership and narrow dependencies.
"""Structural ownership checks complement exact wire-to-snapshot tests."""

import ast
import time

from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

OWNER = "ladder_dragon.market_data.tickers"
OWNER_PATH = "ladder_dragon/market_data/tickers.py"
CONSUMER = "ladder_dragon/execution/tools_market.py"
POLICY = "ladder_dragon/risk/asset_policy.py"


def audit_market_tickers(root):
    tree = ast.parse((root / OWNER_PATH).read_text())
    violations = []
    if (root / "ladder_dragon/execution/market_tickers.py").exists():
        violations.append("tickers:legacy_owner_present")
    expected = {"_indexed_rows": 5, "_prices": 4, "requested_prices": 1, "valuation_prices": 8}
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(definitions) != 4 or {n.name for n in definitions} != set(expected):
        violations.append("tickers:concrete_owner_missing")
    for node in definitions:
        body = [n for n in node.body if not (isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
        if len(body) < expected.get(node.name, 2):
            violations.append("tickers:forwarding_stub")
        if node.name == "requested_prices" and ast.dump(node) != ast.dump(ast.parse(
                'def requested_prices(payload, symbols):\n'
                '    """Return only requested observations; an omitted symbol proves no absence."""\n'
                '    return _prices(_indexed_rows(payload), set(symbols))').body[0]):
            violations.append("tickers:requested_binding_changed")
    for path, allowed in ((OWNER_PATH, {"decimal", "ladder_dragon.risk.asset_policy"}),
                          ("ladder_dragon/market_data/__init__.py", set()), (POLICY, set())):
        for node in ast.walk(ast.parse((root / path).read_text())):
            modules = ([node.module if not node.level else None] if isinstance(node, ast.ImportFrom)
                       else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(module not in allowed for module in modules):
                violations.append(path + ":unexpected_dependency")
    consumer = ast.parse((root / CONSUMER).read_text())
    imports = [(n.module, n.level, a.name, a.asname) for n in consumer.body
               if isinstance(n, ast.ImportFrom) for a in n.names]
    if imports.count((OWNER, 0, "valuation_prices", None)) != 1:
        violations.append("tickers:canonical_import_missing")
    if any((isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == "valuation_prices")
           or (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == "valuation_prices")
           for n in ast.walk(consumer)):
        violations.append("tickers:consumer_binding_replaced")
    return violations


def check_market_tickers(context):
    started = time.monotonic()
    try:
        violations = audit_market_tickers(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations, status = [type(exc).__name__], Status.BLOCKED
    return CheckResult(name="architecture_market_tickers", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Public ticker validation ownership", exit_code=EXIT_CODES[status],
        metrics={"violations": violations})
