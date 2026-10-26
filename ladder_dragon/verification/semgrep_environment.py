# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify and install the isolated downstream static analyzer.
"""Verify the isolated downstream distribution with only standard-library imports."""

import hashlib
import base64
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import re
import sys


def host_key():
    return platform.system().lower() + "-" + platform.machine().lower()


def payload_digest(distribution):
    """Bind actual installed code bytes, not only mutable installed RECORD hashes."""
    entries = {}
    for item in distribution.files or ():
        name = str(item)
        if not name.startswith(("semgrep/", "semdep/")) or name.endswith(".pyc"):
            continue
        path = Path(distribution.locate_file(item))
        if path.is_symlink() or not path.is_file():
            raise ValueError("invalid installed payload")
        entries[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_launchers(distribution):
    """Check pip-generated launchers as well as the pinned package payload."""
    for name in ("semgrep", "pysemgrep"):
        expected = Path(sys.prefix) / "bin" / name
        records = [item for item in distribution.files or ()
                   if Path(distribution.locate_file(item)).absolute() == expected.absolute()
                   or Path(distribution.locate_file(item)).resolve() == expected.resolve()]
        if len(records) != 1 or expected.is_symlink() or not expected.is_file():
            raise ValueError("launcher identity mismatch")
        record = records[0]
        encoded = base64.urlsafe_b64encode(hashlib.sha256(expected.read_bytes()).digest()).rstrip(b"=").decode()
        if record.hash is None or record.hash.mode != "sha256" or record.hash.value != encoded:
            raise ValueError("launcher integrity mismatch")


def verify(root):
    """Reject an upstream package, changed wheel, changed payload, or dependency drift."""
    manifest = json.loads((root / "requirements/semgrep-build.json").read_text())
    target = manifest["platforms"][host_key()]
    expected = dict(re.findall(
        r"^([\w.-]+)(?:\[[^\]]+\])?==([^\s\\]+)",
        (root / "requirements/semgrep.lock").read_text(), re.MULTILINE,
    ))
    if not expected:
        raise ValueError("empty dependency contract")
    expected["semgrep"] = manifest["version"]
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    installed = [normalize(item.metadata["Name"]) for item in metadata.distributions()]
    if len(installed) != len(set(installed)) or set(installed) != {normalize(name) for name in expected}:
        raise ValueError("installed dependency set differs from lock")
    for name, version in expected.items():
        if metadata.version(name) != version:
            raise ValueError("dependency version mismatch")
    distribution = metadata.distribution("semgrep")
    verify_launchers(distribution)
    origin = json.loads(distribution.read_text("direct_url.json") or "{}")
    archive = origin.get("archive_info", {})
    legacy = archive.get("hash")
    current = archive.get("hashes", {}).get("sha256")
    expected_hash = target["wheel_sha256"]
    if (current is None and legacy is None
            or current is not None and current != expected_hash
            or legacy is not None and legacy != "sha256=" + expected_hash):
        raise ValueError("wheel provenance mismatch")
    if payload_digest(distribution) != target["payload_sha256"]:
        raise ValueError("installed payload mismatch")


if __name__ == "__main__":
    try:
        verify(Path(sys.argv[1]))
    except (OSError, ValueError, KeyError, TypeError, metadata.PackageNotFoundError):
        print("Semgrep toolchain verification failed", file=sys.stderr)
        raise SystemExit(2)
