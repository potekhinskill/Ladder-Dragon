# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce history route and reader ownership.
"""Require concrete history handlers and their shared read-only reader."""

import ast
import time
from ladder_dragon.verification.architecture.route_contracts import audit_route_group
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

HISTORY_PATHS = {
    "trades_symbols": "/api/trades/symbols",
    "trades_recent": "/api/trades/recent",
    "api_trades_filled": "/api/trades/filled",
    "api_orders_filled": "/api/orders/filled",
    "api_fills": "/api/fills",
}
HISTORY_FIELDS = frozenset((
    "APP_TZ", "_database_unavailable_response", "_fee_pct_default", "_open_db", "time",
))
ALIAS_BODY = '''syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
items = select_filled_orders(state, hours, syms, limit, offset)
return JSONResponse(items)
'''


def audit_history_routes(root):
    bodies = {name: ALIAS_BODY for name in HISTORY_PATHS}
    bodies.update(trades_symbols="try", trades_recent="try")
    violations = audit_route_group(root, group="history", paths=HISTORY_PATHS,
                                   fields=HISTORY_FIELDS, bodies=bodies)
    reader = ast.parse((root / "ladder_dragon/dashboard/history_reader.py").read_text())
    router = ast.parse((root / "ladder_dragon/dashboard/routers/history.py").read_text())
    runtime = ast.parse((root / "ladder_dragon/dashboard/runtime.py").read_text())
    bindings = [(n.module, a.name, a.asname) for n in router.body if isinstance(n, ast.ImportFrom) for a in n.names]
    if bindings.count(("ladder_dragon.dashboard.history_reader", "select_filled_orders", None)) != 1:
        violations.append("history:reader_binding_changed")
    functions = [n for n in reader.body if isinstance(n, ast.FunctionDef) and n.name == "select_filled_orders"]
    if len(functions) != 1 or not any(isinstance(n, ast.Try) and n.finalbody for n in functions[0].body):
        violations.append("history:reader_owner_missing")
    if any(isinstance(n, ast.FunctionDef) and n.name == "_select_filled_orders" for n in runtime.body):
        violations.append("history:runtime_reader_returned")
    for node in ast.walk(reader):
        modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                   [a.name for a in node.names] if isinstance(node, ast.Import) else [])
        if any(m == "ladder_dragon.dashboard.runtime" or m == "bin" or m.startswith("bin.") for m in modules):
            violations.append("history:reverse_reader_dependency")
    return violations


def check_history_routes(context):
    started = time.monotonic()
    try:
        violations = audit_history_routes(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations = [type(exc).__name__]
        status = Status.BLOCKED
    return CheckResult(name="architecture_history_routes", status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Concrete history routes and shared reader",
                       exit_code=EXIT_CODES[status], metrics={"violations": violations})
