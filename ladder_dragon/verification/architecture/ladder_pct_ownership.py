# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce concrete percentage-ladder component ownership.
"""Structural contracts supplement unchanged financial syntax regressions."""

import ast

LADDER_OWNERS = {
    "math": ("round_down_to_step", "round_up_to_step", "fmt_decimal", "uniq_keep", "thin_ticks", "thin_abs_pct", "raw_levels"),
    "parser": ("parse_args", "parse_percentages"),
    "market": ("die", "calc_atr", "_filters_decimal", "_now_price_decimal"),
    "dispatch": ("check_min_notional", "launch_executor"),
    "command": ("main",),
}
LADDER_LINKS = {
    "parser": {"market": {"die"}},
    "dispatch": {"math": {"fmt_decimal"}, "market": {"die"}},
    "command": {
        "market": {"die", "calc_atr", "_filters_decimal", "_now_price_decimal"},
        "parser": {"parse_args", "parse_percentages"},
        "math": {"round_down_to_step", "round_up_to_step", "fmt_decimal", "uniq_keep", "thin_ticks", "thin_abs_pct", "raw_levels"},
        "dispatch": {"check_min_notional", "launch_executor"},
    },
}


def audit_ladder_owners(root):
    violations = []
    for owner, definitions in LADDER_OWNERS.items():
        tree = ast.parse((root / f"ladder_dragon/strategy/ladder_pct_{owner}.py").read_text(encoding="utf-8"))
        for name in definitions:
            nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
            if name == "_now_price_decimal":
                valid = len(nodes) == 1 and len(nodes[0].body) == 1 and isinstance(nodes[0].body[0], ast.Try)
            else:
                valid = len(nodes) == 1 and len(nodes[0].body) >= 2
            if not valid:
                violations.append(f"ladder_pct_{owner}:{name}:concrete_owner_missing")
        for dependency, names in LADDER_LINKS.get(owner, {}).items():
            imported = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                        and n.module == f"ladder_dragon.strategy.ladder_pct_{dependency}"
                        for a in n.names if a.asname is None}
            if not names <= imported:
                violations.append(f"ladder_pct_{owner}:{dependency}:owner_link_missing")
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"ladder_pct_{owner}:reverse_launcher_dependency")
        if owner == "command":
            expected = ast.parse("from decimal import Decimal, getcontext\ngetcontext().prec = 28\nfrom dotenv import load_dotenv\nload_dotenv()\n")
            if ast.dump(ast.Module(body=tree.body[:4], type_ignores=[])) != ast.dump(expected):
                violations.append("ladder_pct_command:initialization_order_changed")
    return violations
