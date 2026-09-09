# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: inventory source interfaces and deployment resources without executing them.
"""Exact source membership is not proof of installed interface parity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from ladder_dragon.verification.architecture.inventory import (
    MAX_REPORT, PATH, git_inventory, read_source, unique_object,
)


CONTRACT = "schemas/architecture_surfaces.json"
COMMAND_GUIDE = "docs/COMMAND_REFERENCE.md"
ROOTS = ("bin/", "deploy/", "FRONT/", "FastAPI/pi-dashboard/",
         "ladder_dragon/migrations/", "ladder_dragon/strategy/prediction/context_migrations/")
# Exact files remain in the manifest. Patterns constrain their declared roles.
KINDS = {
    "python_command": (r"bin/(?!__init__\.py)[a-z_0-9]+\.py", "operator.commands"),
    "shell_command": (r"bin/[a-z_0-9]+\.sh", "operator.commands"),
    "command_package": (r"bin/__init__\.py", "operator.commands"),
    "asgi_entry": (r"FastAPI/pi-dashboard/app\.py", "dashboard.entrypoint"),
    "frontend_asset": (r"FRONT/[A-Za-z_0-9.-]+\.(?:html|css|js)", "dashboard.assets"),
    "frontend_vendor": (r"FRONT/vendor/[A-Za-z_0-9.-]+\.(?:js|txt)", "dashboard.vendor"),
    "service": (r"deploy/[A-Za-z_0-9.-]+\.service", "deployment.services"),
    "timer": (r"deploy/[A-Za-z_0-9.-]+\.timer", "deployment.services"),
    "deployment_python": (r"deploy/[A-Za-z_0-9.-]+\.py", "deployment.host"),
    "deployment_shell": (r"deploy/[A-Za-z_0-9.-]+\.sh", "deployment.host"),
    "deployment_config": (r"deploy/(?:[A-Za-z_0-9.-]+\.conf(?:\.example)?|"
                          r"nginx/[A-Za-z_0-9.-]+\.conf|system/(?:[A-Za-z_0-9.-]+\.(?:conf|local)|zramswap))",
                          "deployment.host"),
    "accounting_migration": (r"ladder_dragon/migrations/[0-9]+_[a-z_0-9]+\.sql", "persistence.accounting"),
    "context_migration": (r"ladder_dragon/strategy/prediction/context_migrations/[0-9]+_[a-z_0-9]+\.sql",
                          "prediction.context"),
}


def load_surfaces(root: Path) -> tuple[dict[str, str], str]:
    """Reject unknown roles and unsafe or ambiguous manifest entries."""
    raw = read_source(root, CONTRACT, 128 * 1024)
    payload = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "scope", "files"}
            or type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or payload["scope"] != "source_surface_inventory_not_interface_parity"
            or not isinstance(payload["files"], dict) or not 1 <= len(payload["files"]) <= 2048):
        raise ValueError("invalid surface schema")
    for name, kind in payload["files"].items():
        if (not isinstance(kind, str) or kind not in KINDS or not PATH.fullmatch(name)
                or ".." in PurePosixPath(name).parts
                or not re.fullmatch(KINDS[kind][0], name)):
            raise ValueError("invalid surface declaration")
    return payload["files"], hashlib.sha256(raw).hexdigest()


def audit_surfaces(root: Path) -> dict:
    """Observe registered source only; unknown additions fail before content reads."""
    try:
        files, digest = load_surfaces(root)
        names, sha = git_inventory(root)
        discovered = {name for name in names if name.startswith(ROOTS)}
        violations, rows = [], []
        for name in sorted(discovered - files.keys()):
            # Do not echo unknown paths: filenames can contain private material.
            violations.append({"reason": "unregistered_surface"})
        guide = read_source(root, COMMAND_GUIDE, 256 * 1024)
        documented = set(re.findall(r"^\| `([a-z_0-9]+(?:\.sh)?)` \|", guide.decode("utf-8"), re.M))
        for name, kind in sorted(files.items()):
            if name not in discovered:
                violations.append({"path": name, "reason": "registered_surface_outside_inventory"})
                continue
            try:
                source = read_source(root, name, 1024 * 1024)
            except FileNotFoundError:
                violations.append({"path": name, "reason": "registered_surface_missing"})
                continue
            command = PurePosixPath(name).stem if kind == "python_command" else PurePosixPath(name).name
            if kind in {"python_command", "shell_command"} and command not in documented:
                violations.append({"path": name, "reason": "command_missing_from_guide"})
            rows.append({"path": name, "kind": kind, "owner": KINDS[kind][1],
                         "bytes": len(source), "source_sha256": hashlib.sha256(source).hexdigest()})
        counts = {kind: sum(row["kind"] == kind for row in rows) for kind in KINDS}
        result = {"status": "FAILED" if violations else "PASS", "commit_sha": sha,
                  "contract_sha256": digest, "command_guide_sha256": hashlib.sha256(guide).hexdigest(),
                  "source_count": len(rows), "counts": counts, "sources": rows, "violations": violations,
                  "identity_scope": "HEAD plus current source hashes, including nonignored new files",
                  "limits": "Source membership and command guide coverage only; CLI behavior, service references, "
                            "installed assets, package contents, and migration compatibility remain separate checks."}
        if len(json.dumps(result).encode()) > MAX_REPORT:
            raise ValueError("surface report exceeds ceiling")
        return result
    except (OSError, ValueError, UnicodeError, RecursionError, subprocess.SubprocessError):
        return {"status": "BLOCKED", "reason": "architecture_surface_input_unavailable_or_invalid"}
