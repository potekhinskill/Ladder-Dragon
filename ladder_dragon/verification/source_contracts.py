# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: share qualified Abstract Syntax Tree identities across source audits.
"""Shared helpers for structural source-contract audits."""

from __future__ import annotations

import ast


FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def qualified_functions(tree: ast.Module) -> dict[str, FunctionNode]:
    """Index module functions and class methods by qualified identity."""
    functions: dict[str, FunctionNode] = {}

    def collect(body: list[ast.stmt], *, prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                collect(node.body, prefix=prefix + node.name + ".")

    collect(tree.body)
    return functions


def expression_identity(node: ast.AST) -> str:
    """Return one stable dotted identity for a name or attribute."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = expression_identity(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    return ""


__all__ = ["FunctionNode", "expression_identity", "qualified_functions"]
