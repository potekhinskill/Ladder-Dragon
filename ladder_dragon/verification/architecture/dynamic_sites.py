# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: observe dynamic import syntax without executing or exposing expressions.
"""Dynamic import observations do not prove binding identity or reachability."""

from __future__ import annotations

import ast
import hashlib
from importlib.util import resolve_name


def _argument(call: ast.Call, position: int, name: str) -> ast.AST | None:
    values = ([call.args[position]] if len(call.args) > position else [])
    values += [item.value for item in call.keywords if item.arg == name]
    return values[0] if len(values) == 1 else None


def _literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def dynamic_sites(tree: ast.Module, local_modules: set[str]) -> list[dict]:
    """Report only known local targets; hash other arguments without disclosure."""
    modules, functions = set(), {"__import__": "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == "importlib")
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                if (node.module, alias.name) in {("importlib", "import_module"), ("builtins", "__import__")}:
                    functions[alias.asname or alias.name] = alias.name
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = functions.get(node.func.id) if isinstance(node.func, ast.Name) else None
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                and isinstance(node.func.value, ast.Name) and node.func.value.id in modules):
            method = "import_module"
        if method is None:
            continue
        target = _literal(_argument(node, 0, "name"))
        expanded = any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords)
        parameters = ("name", "package") if method == "import_module" else ("name", "globals", "locals", "fromlist", "level")
        supplied = list(parameters[:len(node.args)]) + [k.arg for k in node.keywords]
        invalid = (len(node.args) > len(parameters) or len(supplied) != len(set(supplied))
                   or any(name not in parameters for name in supplied))
        state = "unresolved_expression"
        if expanded or invalid:
            target = None
        elif method == "__import__":
            level = _argument(node, 4, "level")
            if level is not None and not (isinstance(level, ast.Constant) and type(level.value) is int and level.value == 0):
                target = None
        elif target and target.startswith("."):
            package = _literal(_argument(node, 1, "package"))
            if package:
                try:
                    target = resolve_name(target, package)
                except (ImportError, ValueError):
                    target = None
            else:
                target = None
        if target is not None:
            state = "local_literal" if target in local_modules else "external_or_unknown_literal"
        sites.append({"line": node.lineno, "method": method, "resolution": state,
                      "target": target if state == "local_literal" else None,
                      "ast_sha256": hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()})
    return sorted(sites, key=lambda row: (row["line"], row["method"], row["ast_sha256"]))
