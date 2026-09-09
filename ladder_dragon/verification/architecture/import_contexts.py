# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: observe import placement without evaluating guards or runtime names.
"""Context flags describe syntax, not reachable execution or binding provenance."""

import ast


def import_contexts(tree: ast.Module) -> list[tuple[ast.AST, dict]]:
    """Keep every import, including uncertain guards and deferred definitions."""
    typing_names, guard_names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            typing_names.update(a.asname or a.name for a in node.names if a.name == "typing")
        elif isinstance(node, ast.ImportFrom) and node.module == "typing" and not node.level:
            guard_names.update(a.asname or a.name for a in node.names if a.name == "TYPE_CHECKING")

    def type_guard(node: ast.AST) -> bool:
        return ((isinstance(node, ast.Name) and node.id in guard_names)
                or (isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"
                    and isinstance(node.value, ast.Name) and node.value.id in typing_names))

    sites = []
    stack = [(tree, {"deferred": False, "conditional": False, "class_body": False, "type_guard_syntax": False})]
    while stack:
        node, context = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            sites.append((node, context))
        flags = dict(context)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            flags["deferred"] = True
        if isinstance(node, ast.ClassDef):
            flags["class_body"] = True
        if type(node).__name__ in {"If", "For", "AsyncFor", "While", "With", "AsyncWith", "Try", "TryStar", "Match"}:
            flags["conditional"] = True
        for child in reversed(list(ast.iter_child_nodes(node))):
            child_flags = dict(flags)
            if isinstance(node, ast.If) and child in node.body and type_guard(node.test):
                child_flags["type_guard_syntax"] = True
            stack.append((child, child_flags))
    return sorted(sites, key=lambda site: (site[0].lineno, site[0].col_offset))
