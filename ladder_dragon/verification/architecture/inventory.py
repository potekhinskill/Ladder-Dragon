# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: inventory source ownership without importing application modules.
"""Exact directory ownership and the static package-to-launcher boundary."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

from ladder_dragon.verification.architecture.cli_sites import parser_sites
from ladder_dragon.verification.architecture.dynamic_sites import dynamic_sites
from ladder_dragon.verification.architecture.dependency_graph import dependency_graph
from ladder_dragon.verification.architecture.function_spans import function_spans


CONTRACT = "schemas/architecture_contract.json"
PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*\Z")
OWNER = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z")
MAX_REPORT = 2 * 1024 * 1024


def read_source(root: Path, name: str, ceiling: int) -> bytes:
    """Reject links, traversal, and excessive source before parsing."""
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise ValueError("unsafe source path")
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("source symlink")
    if not stat.S_ISREG(candidate.stat().st_mode):
        raise ValueError("source is not a regular file")
    with candidate.open("rb") as stream:
        data = stream.read(ceiling + 1)
    if len(data) > ceiling:
        raise ValueError("source exceeds ceiling")
    return data


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject ambiguous duplicate JSON keys."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate contract key")
        result[key] = value
    return result


def load_contract(root: Path) -> tuple[dict, str]:
    """Validate a narrow owner registry with exact directory semantics."""
    raw = read_source(root, CONTRACT, 65536)
    policy = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(policy, dict)
            or set(policy) != {"schema_version", "scope", "directories", "files"}
            or type(policy["schema_version"]) is not int
            or policy["schema_version"] != 1
            or policy["scope"] != "python_ownership_and_static_launcher_boundary"):
        raise ValueError("invalid contract schema")
    for field in ("directories", "files"):
        mapping = policy[field]
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("missing ownership declarations")
        for name, owner in mapping.items():
            if (not PATH.fullmatch(name) or ".." in PurePosixPath(name).parts
                    or not isinstance(owner, str) or not OWNER.fullmatch(owner)
                    or (field == "files" and not name.endswith(".py"))):
                raise ValueError("invalid owner declaration")
    if any(str(PurePosixPath(name).parent) in policy["directories"]
           for name in policy["files"]):
        raise ValueError("overlapping owner declarations")
    return policy, hashlib.sha256(raw).hexdigest()


def git_inventory(root: Path) -> tuple[list[str], str]:
    """Include tracked and new nonignored files without entering private caches."""
    def run(*args: str) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True,
            timeout=15,
        ).stdout
    raw = run("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if len(raw) > MAX_REPORT:
        raise ValueError("inventory exceeds ceiling")
    names = sorted(set(raw.decode("utf-8").rstrip("\0").split("\0")))
    sha = run("rev-parse", "HEAD").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid commit identity")
    return names, sha


def imports(tree: ast.AST, name: str) -> list[str]:
    """Resolve static absolute and relative targets, including nested scopes."""
    module = PurePosixPath(name).with_suffix("").parts
    package = module[:-1]
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = ()
            if node.level:
                if node.level > len(package):
                    raise ValueError("relative import escapes package")
                prefix = package[:len(package) - node.level + 1]
            base = ".".join((*prefix, *((node.module or "").split(".")))).strip(".")
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return sorted(target for target in targets
                  if target == "bin" or target.startswith(("bin.", "ladder_dragon.")))


def audit(root: Path) -> dict:
    """Return bounded diagnostics; incomplete analysis never grants PASS."""
    try:
        policy, digest = load_contract(root)
        names, sha = git_inventory(root)
        local_modules = {".".join(PurePosixPath(name).with_suffix("").parts).removesuffix(".__init__")
                         for name in names if name.endswith(".py") and PATH.fullmatch(name)
                         and not name.startswith("tests/")}
        rows, violations, trees = [], [], {}
        for name in names:
            if not name.endswith(".py") or name.startswith("tests/"):
                continue
            if not PATH.fullmatch(name):
                violations.append({"rule": "A01", "reason": "unsupported_source_path"})
                continue
            owner = policy["files"].get(name) or policy["directories"].get(str(PurePosixPath(name).parent))
            if owner is None:
                violations.append({"rule": "A01", "path": name, "reason": "unknown_owner"})
                continue
            source = read_source(root, name, 1024 * 1024).decode("utf-8")
            tree = ast.parse(source)
            trees[name] = tree
            targets = imports(tree, name)
            if name.startswith("ladder_dragon/") and any(t == "bin" or t.startswith("bin.") for t in targets):
                violations.append({"rule": "A02", "path": name, "reason": "package_imports_launcher"})
            functions = function_spans(tree)
            rows.append({"path": name, "owner": owner, "lines": len(source.splitlines()),
                         "maximum_function_lines": max((row["lines"] for row in functions), default=0),
                         "functions": functions, "imports": targets,
                         "cli_sites": parser_sites(tree),
                         "dynamic_import_sites": dynamic_sites(tree, local_modules),
                         "source_sha256": hashlib.sha256(source.encode()).hexdigest()})
        result = {"status": "FAILED" if violations else "PASS", "scope": policy["scope"],
                  "commit_sha": sha, "contract_sha256": digest, "sources": rows,
                  "identity_scope": "HEAD plus observed working-tree source hashes, including nonignored new files",
                  "source_count": len(rows), "violations": violations,
                  "function_count": sum(len(row["functions"]) for row in rows),
                  "function_inventory_scope": "Physical spans include decorators and nested bodies; lambdas are excluded. "
                                              "Duplicate lexical names remain separate and ambiguous. No size budgets or runtime identities are proved.",
                  "dependency_graph": dependency_graph(trees),
                  "cli_site_count": sum(len(row["cli_sites"]) for row in rows),
                  "dynamic_import_site_count": sum(len(row["dynamic_import_sites"]) for row in rows),
                  "dynamic_inventory_scope": "Syntactic call observations only; aliases can be shadowed or rebound. "
                                             "Assignment aliases, attribute loaders, reachability, fromlist targets, "
                                             "and runtime bindings are not resolved. Unknown arguments are not printed.",
                  "cli_inventory_scope": "Syntactic observations only; receiver identity, reachability, dynamic declarations, "
                                         "shell commands, defaults, and CLI behavior are not verified.",
                  "limits": "Static imports only; cycles, capabilities, dynamic imports, and size budgets are not enforced."}
        if len(json.dumps(result).encode()) > MAX_REPORT:
            raise ValueError("report exceeds ceiling")
        return result
    except (OSError, UnicodeError, ValueError, SyntaxError, RecursionError, subprocess.SubprocessError):
        return {"status": "BLOCKED", "reason": "architecture_input_unavailable_or_invalid"}
