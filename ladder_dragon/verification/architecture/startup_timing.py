# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce shared startup timing ownership in required profiles.
"""Scoped structural checks complement timing and lifecycle behavior tests."""

import ast
import time

from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

OWNER = "ladder_dragon.observability.startup_timing"
OWNER_PATH = "ladder_dragon/observability/startup_timing.py"
CONSUMERS = {
    "ladder_dragon/execution/worker/lifecycle.py": ("StartupTimeline", "log_worker_startup"),
    "ladder_dragon/supervision/runtime.py": (
        "StartupSubphases", "StartupTimeline", "first_subphase_callback",
        "record_failed_startup_attempt",
    ),
}
FUNCTIONS = {"first_subphase_callback": 2, "record_failed_startup_attempt": 3,
             "log_worker_startup": 3}
METHODS = {"StartupTimeline": {"__init__": 4, "mark": 6, "snapshot": 1},
           "StartupSubphases": {"__init__": 3, "mark": 3, "advance": 1}}


def _concrete(nodes, expected):
    definitions = [n for n in nodes if isinstance(n, ast.FunctionDef)]
    if {n.name for n in definitions} != set(expected) or len(definitions) != len(expected):
        return False
    for node in definitions:
        statements = [n for n in node.body if not (
            isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str))]
        if len(statements) < expected[node.name]:
            return False
    return True


def audit_startup_timing(root):
    owner = ast.parse((root / OWNER_PATH).read_text())
    violations = []
    if (root / "ladder_dragon/supervision/startup_timing.py").exists():
        violations.append("timing:legacy_owner_present")
    classes = [n for n in owner.body if isinstance(n, ast.ClassDef)]
    if not _concrete(owner.body, FUNCTIONS) or {n.name for n in classes} != set(METHODS) or len(classes) != 2:
        violations.append("timing:concrete_owner_missing")
    for cls in classes:
        if cls.name in METHODS and not _concrete(cls.body, METHODS[cls.name]):
            violations.append("timing:concrete_methods_missing")
    for path in (root / "ladder_dragon/observability/__init__.py", root / OWNER_PATH):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module] if not node.level else [None]
            elif isinstance(node, ast.Import):
                modules = [n.name for n in node.names]
            else:
                continue
            if any(m not in {"__future__", "time", "collections.abc", "typing"} for m in modules):
                violations.append("timing:nonstandard_dependency")
    for path, names in CONSUMERS.items():
        tree = ast.parse((root / path).read_text())
        imports = [(n.module, a.name, a.asname) for n in tree.body
                   if isinstance(n, ast.ImportFrom) for a in n.names]
        if any(imports.count((OWNER, name, None)) != 1 for name in names):
            violations.append(path + ":canonical_import_missing")
        if any((isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names)
               or (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in names)
               for n in ast.walk(tree)):
            violations.append(path + ":timing_binding_replaced")
        if path.endswith("lifecycle.py"):
            resources = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "WorkerResources"]
            for name, value in {"startup_timeline": "StartupTimeline", "log_startup": "log_worker_startup"}.items():
                expected = ast.parse(f"{name} = staticmethod({value})").body[0]
                assignments = [n for cls in resources for n in cls.body if isinstance(n, ast.Assign)
                               and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
                if len(assignments) != 1 or ast.dump(assignments[0]) != ast.dump(expected):
                    violations.append("worker:timing_resource_binding_changed")
    return violations


def check_startup_timing(context):
    started = time.monotonic()
    try:
        violations = audit_startup_timing(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations, status = [type(exc).__name__], Status.BLOCKED
    return CheckResult(
        name="architecture_startup_timing", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Shared startup timing ownership and worker bindings",
        exit_code=EXIT_CODES[status], metrics={"violations": violations},
    )
