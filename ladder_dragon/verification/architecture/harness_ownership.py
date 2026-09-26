# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce interpreter-first verification command ownership.
"""The bootstrap must stay independent of verification dependencies."""

import ast

HARNESS_OWNERS = {
    "ladder_dragon.harness_bootstrap": ("_project_venv_python", "_reexec_project_venv_if_needed"),
    "ladder_dragon.verification.harness_parser": ("build_parser",),
    "ladder_dragon.verification.harness_options": ("prepare_options",),
    "ladder_dragon.verification.harness_identity": ("_commit_sha",),
    "ladder_dragon.verification.harness_command": ("main",),
}
HARNESS_LINKS = {
    "ladder_dragon.verification.harness_identity": {
        "ladder_dragon.harness_bootstrap": {"PROJECT_ROOT"},
    },
    "ladder_dragon.verification.harness_options": {
        "ladder_dragon.verification.models": {"HarnessOptions"},
    },
    "ladder_dragon.verification.harness_command": {
        "ladder_dragon.harness_bootstrap": {"PROJECT_ROOT"},
        "ladder_dragon.verification.harness_identity": {"_commit_sha"},
        "ladder_dragon.verification.harness_parser": {"build_parser"},
        "ladder_dragon.verification.harness_options": {"prepare_options"},
        "ladder_dragon.verification.runner": {"HarnessRunner"},
        "ladder_dragon.verification.report": {"build_report", "write_report"},
    },
}
HARNESS_LAUNCHER = '''from ladder_dragon.harness_bootstrap import _reexec_project_venv_if_needed
if __name__ == "__main__":
    _reexec_project_venv_if_needed()
from ladder_dragon.verification.harness_command import main
if __name__ == "__main__":
    raise SystemExit(main())
'''


def audit_harness_owners(root):
    violations = []
    initializer = ast.parse((root / "ladder_dragon/__init__.py").read_text(encoding="utf-8"))
    if any(not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)
           or not isinstance(n.value.value, str) for n in initializer.body):
        violations.append("harness:package_initializer_not_inert")
    for owner, definitions in HARNESS_OWNERS.items():
        tree = ast.parse((root / (owner.replace(".", "/") + ".py")).read_text(encoding="utf-8"))
        for name in definitions:
            matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
            minimum = 2 if name == "_commit_sha" else 3
            if len(matches) != 1 or len(matches[0].body) < minimum:
                violations.append(f"{owner}:{name}:concrete_owner_missing")
        for dependency, names in HARNESS_LINKS.get(owner, {}).items():
            imported = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                        and n.module == dependency for a in n.names if a.asname is None}
            if not names <= imported:
                violations.append(f"{owner}:{dependency}:owner_link_missing")
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"{owner}:reverse_launcher_dependency")
            if owner == "ladder_dragon.harness_bootstrap" and any(
                m not in {"__future__", "os", "sys", "pathlib"} for m in modules
            ):
                violations.append("harness:bootstrap_dependency_import")
        if owner == "ladder_dragon.harness_bootstrap":
            roots = [n for n in tree.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "PROJECT_ROOT" for t in n.targets)]
            expected = ast.parse("PROJECT_ROOT = Path(__file__).resolve().parents[1]").body[0]
            if len(roots) != 1 or ast.dump(roots[0]) != ast.dump(expected):
                violations.append("harness:checkout_root_changed")
    return violations
