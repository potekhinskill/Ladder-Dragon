# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce shared latency trace ownership without execution dependencies.
"""Scoped structural checks complement syntax and persistence regressions."""

import ast
import time

from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

OWNER = "ladder_dragon.observability.latency_trace"
OWNER_PATH = "ladder_dragon/observability/latency_trace.py"
CONSUMERS = ("ladder_dragon/supervision/runtime.py", "ladder_dragon/execution/worker/runtime.py")


def audit_latency_trace(root):
    tree = ast.parse((root / OWNER_PATH).read_text())
    violations = []
    if (root / "ladder_dragon/execution/latency_trace.py").exists():
        violations.append("latency_trace:legacy_owner_present")
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LatencyTrace"]
    if len(classes) != 1:
        violations.append("latency_trace:concrete_owner_missing")
    else:
        methods = [n for n in classes[0].body if isinstance(n, ast.FunctionDef)]
        if len(methods) != 4 or {n.name for n in methods} != {"__post_init__", "mark", "payload", "append"}:
            violations.append("latency_trace:methods_missing")
        for node in methods:
            body = [n for n in node.body if not (isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
            minimum = {"__post_init__": 4, "mark": 6, "payload": 1, "append": 7}.get(node.name, 2)
            if len(body) < minimum or (node.name == "payload" and not (
                    isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Dict))):
                violations.append("latency_trace:forwarding_stub")
    allowed = {"__future__", "json", "os", "time", "uuid", "dataclasses", "pathlib", "typing"}
    for node in ast.walk(tree):
        modules = ([node.module if not node.level else None] if isinstance(node, ast.ImportFrom)
                   else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
        if any(module not in allowed for module in modules):
            violations.append("latency_trace:nonstandard_dependency")
    for path in CONSUMERS:
        consumer = ast.parse((root / path).read_text())
        imports = [(n.module, n.level, a.name, a.asname) for n in consumer.body
                   if isinstance(n, ast.ImportFrom) for a in n.names]
        if imports.count((OWNER, 0, "LatencyTrace", None)) != 1:
            violations.append(path + ":canonical_import_missing")
        if any((isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == "LatencyTrace")
               or (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == "LatencyTrace")
               for n in ast.walk(consumer)):
            violations.append(path + ":trace_binding_replaced")
    return violations


def check_latency_trace(context):
    started = time.monotonic()
    try:
        violations = audit_latency_trace(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations, status = [type(exc).__name__], Status.BLOCKED
    return CheckResult(
        name="architecture_latency_trace", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Shared latency trace ownership", exit_code=EXIT_CODES[status],
        metrics={"violations": violations},
    )
