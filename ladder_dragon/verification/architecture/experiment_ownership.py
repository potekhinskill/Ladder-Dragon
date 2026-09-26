# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce concrete experiment command owners.
"""Structural ownership supplements lifecycle and source parity regressions."""

import ast

EXPERIMENT_OWNERS = {
    "parser": ("_parser",),
    "provenance": ("_source_commit",),
    "evidence": ("_freeze_horizons", "_entry_veto_inputs", "_selection_variants", "_preselected_episode_variant"),
    "actions": ("handle_finalize", "handle_supersede", "handle_entry_veto_freeze",
                "handle_entry_veto_import_history", "handle_champion_preview", "handle_champion_activate",
                "handle_episode_bootstrap", "handle_model_validation_import", "handle_freeze"),
    "command": ("main",),
}
EXPERIMENT_LINKS = {
    "actions": {"provenance": {"_source_commit"}, "evidence": set(EXPERIMENT_OWNERS["evidence"])},
    "command": {"parser": {"_parser"}, "evidence": {"_entry_veto_inputs"},
                "actions": set(EXPERIMENT_OWNERS["actions"])},
}


def audit_experiment_owners(root):
    violations = []
    for owner, definitions in EXPERIMENT_OWNERS.items():
        tree = ast.parse((root / f"ladder_dragon/strategy/prediction/experiment_{owner}.py").read_text(encoding="utf-8"))
        for name in definitions:
            nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
            statements = ([] if len(nodes) != 1 else [n for n in nodes[0].body
                          if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))])
            if name == "_freeze_horizons":
                expected = ast.parse("return experiment_spec_for_generation(generation, symbol=symbol).horizons_min").body
                valid = ast.dump(ast.Module(body=statements, type_ignores=[])) == ast.dump(ast.Module(body=expected, type_ignores=[]))
            else:
                valid = len(statements) >= 2
            if not valid:
                violations.append(f"experiment_{owner}:{name}:concrete_owner_missing")
        for dependency, names in EXPERIMENT_LINKS.get(owner, {}).items():
            imported = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                        and n.module == f"ladder_dragon.strategy.prediction.experiment_{dependency}"
                        for a in n.names if a.asname is None}
            if not names <= imported:
                violations.append(f"experiment_{owner}:{dependency}:owner_link_missing")
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"experiment_{owner}:reverse_launcher_dependency")
    return violations
