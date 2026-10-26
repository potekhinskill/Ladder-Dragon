# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce one context-local read telemetry owner across layers.
"""Structural telemetry ownership complements producer and isolation tests."""

import ast
import time

from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

OWNER = "ladder_dragon.observability.read_timing"
OWNER_PATH = "ladder_dragon/observability/read_timing.py"
CONSUMERS = {
    "ladder_dragon/execution/tools_market.py": (("record_read", None), ("measured_read", None)),
    "ladder_dragon/supervision/valuation_metrics.py": (("COUNTERS", "READ_COUNTERS"), ("observe_reads", None)),
    "ladder_dragon/supervision/valuation_reads.py": (("record_read", None),),
}


def audit_read_timing(root):
    tree = ast.parse((root / OWNER_PATH).read_text())
    violations = []
    if (root / "ladder_dragon/execution/read_timing.py").exists():
        violations.append("read_timing:legacy_owner_present")
    expected = {"observe_reads", "record_read", "measured_read"}
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(definitions) != 3 or {n.name for n in definitions} != expected:
        violations.append("read_timing:concrete_owner_missing")
    for node in definitions:
        body = [s for s in node.body if not (
            isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
        if len(body) < 2:
            violations.append("read_timing:forwarding_stub")
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "_sink" for t in n.targets)]
    sink = ast.parse('_sink = ContextVar("public_read_timing", default=None)').body[0]
    stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "_sink"
              and isinstance(n.ctx, ast.Store)]
    if len(assignments) != 1 or len(stores) != 1 or ast.dump(assignments[0]) != ast.dump(sink):
        violations.append("read_timing:context_owner_changed")
    for node in ast.walk(tree):
        modules = ([node.module if not node.level else None] if isinstance(node, ast.ImportFrom)
                   else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
        if any(m not in {"contextlib", "contextvars", "time"} for m in modules):
            violations.append("read_timing:nonstandard_dependency")
    for path, names in CONSUMERS.items():
        consumer = ast.parse((root / path).read_text())
        imports = [(n.module, a.name, a.asname) for n in consumer.body
                   if isinstance(n, ast.ImportFrom) for a in n.names]
        if any(imports.count((OWNER, name, alias)) != 1 for name, alias in names):
            violations.append(path + ":canonical_import_missing")
        protected = {alias or name for name, alias in names}
        if any((isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in protected)
               or (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in protected)
               for n in ast.walk(consumer)):
            violations.append(path + ":telemetry_binding_replaced")
    return violations


def check_read_timing(context):
    started = time.monotonic()
    try:
        violations = audit_read_timing(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations, status = [type(exc).__name__], Status.BLOCKED
    return CheckResult(
        name="architecture_read_timing", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Shared context-local read telemetry ownership",
        exit_code=EXIT_CODES[status], metrics={"violations": violations},
    )
