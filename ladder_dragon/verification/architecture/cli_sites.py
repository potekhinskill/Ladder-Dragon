# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: locate command parser declarations without evaluating defaults.
"""Syntactic CLI sites are observations, not executable interface contracts."""

from __future__ import annotations

import ast
import hashlib


METHODS = frozenset({"add_argument", "add_parser", "add_subparsers", "add_argument_group",
                     "add_mutually_exclusive_group", "set_defaults", "parse_args", "parse_known_args",
                     "parse_intermixed_args", "parse_known_intermixed_args"})


def parser_sites(tree: ast.Module) -> list[dict]:
    """Include nested and conditional sites, with no binding or reachability claim."""
    modules, constructors = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == "argparse")
        elif isinstance(node, ast.ImportFrom) and node.module == "argparse" and not node.level:
            constructors.update(alias.asname or alias.name for alias in node.names if alias.name == "ArgumentParser")
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = None
        if isinstance(node.func, ast.Name) and node.func.id in constructors:
            method = "ArgumentParser"
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in METHODS:
                method = node.func.attr
            elif (node.func.attr == "ArgumentParser" and isinstance(node.func.value, ast.Name)
                  and node.func.value.id in modules):
                method = "ArgumentParser"
        if method is None:
            continue
        # Hash the full syntax, but never publish defaults, help text, or argument values.
        digest = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        literal_count = sum(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in node.args)
        sites.append({"line": node.lineno, "method": method, "ast_sha256": digest,
                      "positional_count": len(node.args), "literal_string_count": literal_count,
                      "keyword_count": len(node.keywords),
                      "expanded_arguments": any(isinstance(arg, ast.Starred) for arg in node.args)
                                            or any(keyword.arg is None for keyword in node.keywords)})
    return sorted(sites, key=lambda row: (row["line"], row["method"]))
