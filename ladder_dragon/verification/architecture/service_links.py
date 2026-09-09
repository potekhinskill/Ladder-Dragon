# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: check literal service targets without running host administration.
"""Source links do not prove shell control flow or installed state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex

from ladder_dragon.verification.architecture.inventory import MAX_REPORT, read_source, unique_object
from ladder_dragon.verification.architecture.surfaces import load_surfaces

CONTRACT = "schemas/architecture_service_links.json"
INSTALLER = "deploy/install_runtime_assets.sh"
PROJECT = "/home/bot/apps/binance_bot/"


def directives(source: str, timer: bool) -> list[tuple[str, str]]:
    """Support the reviewed one-line unit syntax and preserve directive order."""
    section, result = "", []
    for line in source.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line
        if "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if ((not timer and section == "[Service]" and key.startswith("Exec"))
                or (timer and section == "[Timer]" and key == "Unit")):
            if not value or value.endswith("\\"):
                raise ValueError("unsupported directive")
            result.append((key, value))
    return result


def install_links(source: str) -> dict[str, str]:
    """Observe literal install statements, not their reachability or execution."""
    links = {}
    pattern = (r'install -o root -g root -m (?:0644|0755)\s+'
               r'"\$\{PROJECT_DIR\}/(deploy/[\w.-]+)"\s+(/usr/local/[\w/.-]+)')
    for line in source.replace("\\\n", " ").splitlines():
        match = re.fullmatch(pattern, line.strip())
        if match:
            if match[2] in links:
                raise ValueError("duplicate install destination")
            links[match[2]] = match[1]
    return links


def executable_target(value: str, installed: dict[str, str]) -> str | None:
    """Resolve only reviewed executable forms; never evaluate shell expressions."""
    words = shlex.split(value)
    if not words:
        return None
    executable = words[0].removeprefix("+")
    if executable == PROJECT + ".venv/bin/python" and len(words) >= 3 and words[1] == "-m":
        if re.fullmatch(r"bin\.[a-z_0-9]+", words[2]):
            return words[2].replace(".", "/") + ".py"
        return None
    if executable == "/usr/bin/python3" and len(words) >= 2:
        return installed.get(words[1])
    if executable == "/usr/bin/systemctl" and len(words) == 3 and words[1] == "try-restart":
        return "deploy/" + words[2] if re.fullmatch(r"[a-z_0-9.-]+\.service", words[2]) else None
    if executable.startswith(PROJECT):
        return executable[len(PROJECT):]
    return installed.get(executable)


def load_links(root: Path, surfaces: dict) -> tuple[dict, str]:
    """Bind manifest paths to registered public source before reading targets."""
    raw = read_source(root, CONTRACT, 65536)
    payload = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "scope", "units", "installed_files"}
            or type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or payload["scope"] != "literal_service_and_install_source_links"
            or not isinstance(payload["units"], dict) or not isinstance(payload["installed_files"], dict)):
        raise ValueError("invalid link schema")
    for path, rows in payload["units"].items():
        if surfaces.get(path) not in {"service", "timer"} or not isinstance(rows, list) or len(rows) > 16:
            raise ValueError("invalid unit record")
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"directive", "sha256"}
                    or not isinstance(row["directive"], str) or not re.fullmatch(r"Exec[A-Za-z]+|Unit", row["directive"])
                    or not isinstance(row["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])):
                raise ValueError("invalid directive record")
    for destination, source in payload["installed_files"].items():
        if (not re.fullmatch(r"/usr/local/(?:bin|libexec/ladder-dragon)/[A-Za-z_0-9.-]+", destination)
                or not isinstance(source, str) or surfaces.get(source) not in {"deployment_python", "deployment_shell"}):
            raise ValueError("invalid installation record")
    return payload, hashlib.sha256(raw).hexdigest()


def audit_service_links(root: Path) -> dict:
    """Fail stale links and retain only sanitized observations and source hashes."""
    try:
        surfaces, surface_digest = load_surfaces(root)
        payload, digest = load_links(root, surfaces)
        hashes, violations, edges = {}, [], []

        def source(path):
            raw = read_source(root, path, 1024 * 1024)
            hashes[path] = hashlib.sha256(raw).hexdigest()
            return raw.decode("utf-8")

        units = {path for path, kind in surfaces.items() if kind in {"service", "timer"}}
        if units != set(payload["units"]):
            violations.append({"reason": "unit_manifest_coverage_mismatch"})
        if install_links(source(INSTALLER)) != payload["installed_files"]:
            violations.append({"reason": "literal_install_links_changed"})
        for target in set(payload["installed_files"].values()):
            source(target)
        for path, expected in payload["units"].items():
            timer = surfaces[path] == "timer"
            observed = directives(source(path), timer)
            fingerprints = [{"directive": key, "sha256": hashlib.sha256(value.encode()).hexdigest()}
                            for key, value in observed]
            if fingerprints != expected:
                violations.append({"path": path, "reason": "unit_directives_changed"})
            if timer:
                targets = [("Unit", "deploy/" + value) for _, value in observed]
                if not targets:
                    targets = [("Unit", path.removesuffix(".timer") + ".service")]
            else:
                targets = [(key, executable_target(value, payload["installed_files"])) for key, value in observed]
                if not any(key == "ExecStart" for key, _ in observed):
                    violations.append({"path": path, "reason": "missing_exec_start"})
            for key, target in targets:
                allowed = {"service"} if timer else {"service", "python_command", "shell_command", "deployment_shell", "deployment_python"}
                if target not in surfaces or surfaces[target] not in allowed:
                    violations.append({"path": path, "reason": "unresolved_service_target"})
                    continue
                source(target)
                edges.append({"source": path, "directive": key, "target": target})
        result = {"status": "FAILED" if violations else "PASS", "contract_sha256": digest,
                  "surface_contract_sha256": surface_digest, "source_hashes": hashes,
                  "edges": edges, "unit_count": len(payload["units"]),
                  "installation_count": len(payload["installed_files"]), "violations": violations,
                  "limits": "Literal source links only; shell reachability, nested script commands, installed destinations, "
                            "drop-ins, and runtime behavior are not proved."}
        if len(json.dumps(result).encode()) > MAX_REPORT:
            raise ValueError("link report exceeds ceiling")
        return result
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {"status": "BLOCKED", "reason": "architecture_service_link_input_unavailable_or_invalid"}
