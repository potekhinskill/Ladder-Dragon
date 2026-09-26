# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve explicit runtime entry points and live worker state ownership.
"""Source-only checks; never import or start the trading runtimes."""

import ast

from ladder_dragon.verification.authority_bindings import _module_bindings

RUNTIME_COMMANDS = {
    "ai_supervisor": ("ladder_dragon.supervision.runtime", "run_for_symbol", "Ladder Dragon supervisor command."),
    "autosize_universal": ("ladder_dragon.execution.worker.bootstrap", "main", "Ladder Dragon execution-worker command."),
}
INERT_PACKAGES = (
    "ladder_dragon/execution/__init__.py",
    "ladder_dragon/execution/worker/__init__.py",
    "ladder_dragon/supervision/__init__.py",
)
WORKER_MAIN = '''def main() -> None:
    """Start one worker using the live runtime module namespace."""
    from ladder_dragon.execution.worker import runtime
    from ladder_dragon.execution.worker.lifecycle import (
        WorkerRuntimeState,
        run_worker,
    )
    return run_worker(WorkerRuntimeState(vars(runtime)))
'''


def audit_runtime_entries(root):
    violations = []
    for name, (owner, definition, _doc) in RUNTIME_COMMANDS.items():
        path = root / (owner.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bindings = _module_bindings(tree)
        for required in {"main", definition}:
            if bindings.count(required) != 1:
                violations.append(f"{name}:{required}:entry_binding_changed")
        if name == "autosize_universal":
            # Preserve lazy imports and the live namespace; no copied snapshot.
            expected = ast.parse(WORKER_MAIN).body[0]
            mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
            if len(mains) != 1 or ast.dump(mains[0]) != ast.dump(expected):
                violations.append("worker:live_namespace_bootstrap_changed")
            allowed = [n for n in tree.body if not (
                isinstance(n, ast.FunctionDef) and n.name == "main"
                or isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                or isinstance(n, ast.ImportFrom) and n.module == "__future__"
                and [(a.name, a.asname) for a in n.names] == [("annotations", None)]
            )]
            if allowed:
                violations.append("worker:eager_bootstrap_logic")
    for relative in INERT_PACKAGES:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        if any(not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)
               or not isinstance(n.value.value, str) for n in tree.body):
            violations.append(f"{relative}:package_initializer_not_inert")
    return violations
