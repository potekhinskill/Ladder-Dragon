# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: map static imports to observed source files without importing them.
"""Conservative source graph and cycle observations, not runtime reachability."""

from __future__ import annotations

import ast
from pathlib import PurePosixPath

from ladder_dragon.verification.architecture.import_contexts import import_contexts


def module_name(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _targets(tree: ast.AST, path: str) -> set[str]:
    package = PurePosixPath(path).with_suffix("").parts[:-1]
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(package):
                raise ValueError("relative import escapes package")
            prefix = package[:len(package) - node.level + 1] if node.level else ()
            base = ".".join((*prefix, *((node.module or "").split(".")))).strip(".")
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return targets


def cycle_groups(edges: dict[str, set[str]]) -> list[list[str]]:
    """Iterative strongly connected components avoid recursion on long chains."""
    visited, finished = set(), []
    for start in sorted(edges):
        stack = [(start, False)]
        while stack:
            node, complete = stack.pop()
            if complete:
                finished.append(node)
            elif node not in visited:
                visited.add(node)
                stack.append((node, True))
                stack.extend((target, False) for target in sorted(edges[node], reverse=True) if target not in visited)
    reverse = {node: set() for node in edges}
    for node, targets in edges.items():
        for target in targets:
            reverse[target].add(node)
    visited, groups = set(), []
    for start in reversed(finished):
        if start in visited:
            continue
        members, stack = [], [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            members.append(node)
            for target in sorted(reverse[node]):
                if target not in visited:
                    visited.add(target)
                    stack.append(target)
        if len(members) > 1 or start in edges[start]:
            groups.append(sorted(members))
    return sorted(groups)


def dependency_graph(trees: dict[str, ast.Module]) -> dict:
    """Map candidate targets and package initializers to exact inventoried files."""
    modules = {}
    for path in sorted(trees):
        name = module_name(path)
        if name in modules:
            raise ValueError("ambiguous local module")
        modules[name] = path
    direct = {path: set() for path in trees}
    initializers = {path: set() for path in trees}
    unguarded = {path: set() for path in trees}
    context_sites = []
    for path, tree in trees.items():
        for node, context in import_contexts(tree):
            site_direct, site_initializers = set(), set()
            for target in _targets(node, path):
                parts = target.split(".")
                for length in range(1, len(parts) + 1):
                    candidate = modules.get(".".join(parts[:length]))
                    if candidate and (length == len(parts) or candidate.endswith("/__init__.py")):
                        # The currently executing initializer is not a new dependency.
                        if candidate != path or not path.endswith("/__init__.py"):
                            destination = site_direct if length == len(parts) else site_initializers
                            destination.add(candidate)
            direct[path].update(site_direct)
            initializers[path].update(site_initializers)
            if not context["deferred"] and not context["conditional"]:
                unguarded[path].update(site_direct)
            if site_direct or site_initializers:
                context_sites.append({"path": path, "line": node.lineno, "column": node.col_offset,
                                      **context, "direct_targets": sorted(site_direct),
                                      "initializer_targets": sorted(site_initializers)})
    edges = {path: direct[path] | initializers[path] for path in trees}
    cycles = cycle_groups(edges)
    direct_cycles = cycle_groups(direct)
    groups = []
    for members in cycles:
        member_set = set(members)
        inside_direct = sum(len(direct[path] & member_set) for path in members)
        inside_initializers = sum(len((initializers[path] - direct[path]) & member_set) for path in members)
        groups.append({"members": members, "direct_edge_count": inside_direct,
                       "initializer_only_edge_count": inside_initializers,
                       "direct_cycles": [group for group in direct_cycles if set(group) <= member_set]})
    return {"edges": {path: sorted(targets) for path, targets in sorted(edges.items())},
            "direct_edges": {path: sorted(targets) for path, targets in sorted(direct.items())},
            "initializer_edges": {path: sorted(targets) for path, targets in sorted(initializers.items())},
            "edge_count": sum(map(len, edges.values())), "cycles": cycles,
            "direct_cycles": direct_cycles, "cycle_details": groups,
            "import_contexts": sorted(context_sites, key=lambda site: (site["path"], site["line"], site["column"])),
            "unguarded_direct_cycles": cycle_groups(unguarded),
            "context_scope": "Flags describe syntax only. Type-guard aliases can be shadowed or rebound. "
                             "Unguarded imports do not prove startup execution; full edges retain every observed context.",
            "scope": "Static candidate imports and package initializers only. Conditional and nested imports are included. "
                     "Attribute versus submodule binding, external resolution, dynamic loaders, and runtime reachability "
                     "remain unproved. Cycles are observations, not approved exceptions or enforced budgets."}
