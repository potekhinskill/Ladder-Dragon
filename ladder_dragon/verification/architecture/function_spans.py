# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: measure lexical function definitions without executing source.
"""Physical spans are observations, not runtime identity or approved budgets."""

import ast
from collections import Counter


def function_spans(tree: ast.AST) -> list[dict]:
    """Retain duplicate definitions; decorators and nested bodies count in spans."""
    rows = []
    stack = [(tree, ())]
    while stack:
        node, scope = stack.pop()
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = (*scope, node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = min([node.lineno, *[item.lineno for item in node.decorator_list]])
                end = node.end_lineno
                if end is None or start < 1 or end < node.lineno:
                    raise ValueError("invalid function span")
                rows.append({"qualified_name": ".".join(scope), "definition_line": node.lineno,
                             "start_line": start, "end_line": end, "lines": end - start + 1,
                             "async": isinstance(node, ast.AsyncFunctionDef)})
        stack.extend((child, scope) for child in reversed(list(ast.iter_child_nodes(node))))
    counts = Counter(row["qualified_name"] for row in rows)
    for row in rows:
        row["ambiguous_identity"] = counts[row["qualified_name"]] > 1
    return sorted(rows, key=lambda row: (row["definition_line"], row["qualified_name"]))
