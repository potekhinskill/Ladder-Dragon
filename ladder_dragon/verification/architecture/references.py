# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind architecture navigation to existing source authorities.
"""Source references are observations, never new mutation permissions."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re

from ladder_dragon.verification.architecture.inventory import read_source, unique_object, PATH, MAX_REPORT


REFERENCE_MAP = "schemas/architecture_reference_map.json"
IDENTITY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
FIELDS = {"id", "kind", "path", "anchors", "data_class", "review_phase"}


def load_references(root: Path) -> tuple[list[dict], str]:
    """Reject ambiguous records and paths outside reviewed source areas."""
    raw = read_source(root, REFERENCE_MAP, 65536)
    payload = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "scope", "records"}
            or type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or payload["scope"] != "reviewed_source_references_not_writer_authorization"
            or not isinstance(payload["records"], list) or not 1 <= len(payload["records"]) <= 128):
        raise ValueError("invalid reference schema")
    identities = set()
    for item in payload["records"]:
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise ValueError("invalid reference fields")
        if (not all(isinstance(item[key], str) for key in FIELDS - {"anchors"})
                or not IDENTITY.fullmatch(item["id"]) or item["id"] in identities
                or item["kind"] not in {"store", "binding"}
                or item["data_class"] not in {"authoritative", "derived", "disposable", "mixed", "source_policy"}
                or (item["kind"] == "binding") != (item["data_class"] == "source_policy")
                or not re.fullmatch(r"P[0-7]", item["review_phase"])
                or not PATH.fullmatch(item["path"]) or not item["path"].endswith(".py")
                or not item["path"].startswith(("ladder_dragon/", "bin/", "tests/"))
                or not isinstance(item["anchors"], list) or not 1 <= len(item["anchors"]) <= 32):
            raise ValueError("invalid reference record")
        if any(not isinstance(anchor, str) or not IDENTITY.fullmatch(anchor) for anchor in item["anchors"]):
            raise ValueError("invalid reference anchor")
        if len(item["anchors"]) != len(set(item["anchors"])):
            raise ValueError("duplicate reference anchor")
        identities.add(item["id"])
    return payload["records"], hashlib.sha256(raw).hexdigest()


def resolve_anchor(tree: ast.Module, kind: str, anchor: str) -> ast.AST | None:
    """Find concrete definitions or direct assignments without executing them."""
    functions = {}
    duplicates = set()

    def collect(container, prefix=""):
        for node in container.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                if name in functions:
                    duplicates.add(name)
                functions[name] = node
                if isinstance(node, ast.ClassDef):
                    collect(node, name + ".")

    collect(tree)
    for name in list(functions):
        if any(name == duplicate or name.startswith(duplicate + ".") for duplicate in duplicates):
            del functions[name]
    if kind == "store":
        node = functions.get(anchor)
        return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
    scope, _, name = anchor.rpartition(".")
    container = functions.get(scope) if scope else tree
    if container is None:
        return None
    values = []
    for node in container.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            values.append(node.value)
    return values[0] if len(values) == 1 else None


def audit_references(root: Path) -> dict:
    """Detect stale map references while keeping source policies authoritative."""
    try:
        records, digest = load_references(root)
        observed, violations = [], []
        for item in records:
            raw = read_source(root, item["path"], 1024 * 1024)
            tree = ast.parse(raw.decode("utf-8"))
            anchors = []
            for identity in item["anchors"]:
                node = resolve_anchor(tree, item["kind"], identity)
                if node is None:
                    violations.append({"id": item["id"], "anchor": identity, "reason": "missing_or_ambiguous_anchor"})
                    continue
                anchors.append({"identity": identity,
                                "ast_sha256": hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()})
            observed.append({**item, "anchors": anchors, "source_sha256": hashlib.sha256(raw).hexdigest()})
        result = {"status": "FAILED" if violations else "PASS", "map_sha256": digest,
                  "records": observed, "record_count": len(observed), "violations": violations,
                  "limits": "Reviewed anchors only; this is not a complete writer inventory or semantic safety proof."}
        if len(json.dumps(result).encode()) > MAX_REPORT:
            raise ValueError("reference report exceeds ceiling")
        return result
    except (OSError, ValueError, SyntaxError, UnicodeError, RecursionError):
        return {"status": "BLOCKED", "reason": "architecture_reference_input_unavailable_or_invalid"}
