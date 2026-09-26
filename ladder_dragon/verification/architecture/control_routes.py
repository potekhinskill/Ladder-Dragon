# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce advisory-control route and snapshot ownership.
"""Explicit POST and async contracts extend the shared route analyzer."""

import ast
import time
from ladder_dragon.verification.architecture.route_contracts import audit_route_group
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

CONTROL_PATHS = {"ai_control": "/api/ai/control", "set_ai_control": "/api/ai/control"}
CONTROL_FIELDS = frozenset((
    "AI_CONTROL_FILE", "AI_MODE", "_load_ai_runtime_status", "read_ai_control", "write_ai_control",
))


def audit_control_routes(root):
    violations = audit_route_group(
        root, group="control", paths=CONTROL_PATHS, fields=CONTROL_FIELDS,
        bodies={"ai_control": 4, "set_ai_control": "try"},
        methods={"set_ai_control": "post"}, async_names=("set_ai_control",),
    )
    snapshot = ast.parse((root / "ladder_dragon/dashboard/control_snapshot.py").read_text())
    router = ast.parse((root / "ladder_dragon/dashboard/routers/control.py").read_text())
    runtime = ast.parse((root / "ladder_dragon/dashboard/runtime.py").read_text())
    bindings = [(n.module, a.name, a.asname) for n in router.body if isinstance(n, ast.ImportFrom) for a in n.names]
    if bindings.count(("ladder_dragon.dashboard.control_snapshot", "control_snapshot", None)) != 1:
        violations.append("control:snapshot_binding_changed")
    functions = [n for n in snapshot.body if isinstance(n, ast.FunctionDef) and n.name == "control_snapshot"]
    if len(functions) != 1 or not any(isinstance(n, ast.Try) and n.handlers for n in functions[0].body):
        violations.append("control:snapshot_owner_missing")
    if any(isinstance(n, ast.FunctionDef) and n.name == "_ai_control_snapshot" for n in runtime.body):
        violations.append("control:runtime_snapshot_returned")
    for node in ast.walk(snapshot):
        modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                   [a.name for a in node.names] if isinstance(node, ast.Import) else [])
        if any(m == "ladder_dragon.dashboard.runtime" or m == "bin" or m.startswith("bin.") for m in modules):
            violations.append("control:reverse_snapshot_dependency")
    return violations


def check_control_routes(context):
    started = time.monotonic()
    try:
        violations = audit_control_routes(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations = [type(exc).__name__]
        status = Status.BLOCKED
    return CheckResult(name="architecture_control_routes", status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Concrete advisory-control routes and snapshot",
                       exit_code=EXIT_CODES[status], metrics={"violations": violations})
