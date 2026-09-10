# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: inspect release-owned files without deleting local state.
"""Bounded, read-only revision of checkout and installed release files."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

from ladder_dragon.verification.dashboard_assets import DASHBOARD_ASSETS

SCOPES = ("ladder_dragon", "bin", "deploy", "FRONT", "FastAPI/pi-dashboard")
PUBLIC_SOURCES = {source for source, _ in DASHBOARD_ASSETS} | {"schemas/architecture_service_links.json"}
PRIVATE = {"data", "db", "logs", "backups", "__pycache__"}
CODE = {".py", ".pyc", ".pyo", ".so", ".sh", ".js", ".css", ".html", ".service", ".timer"}
MAX_ENTRIES = 20000
MAX_BYTES = 16 * 1024 * 1024


def _git(root, *args):
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args], capture_output=True, timeout=30)
    if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError("release_history_unavailable")
    return result.stdout


def _included(name):
    parts = PurePosixPath(name).parts
    return not any(part.startswith(".") or part in PRIVATE for part in parts)


def _tree(root, sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid_release_sha")
    files = {}
    for row in _git(root, "ls-tree", "-rz", sha).split(b"\0"):
        if not row:
            continue
        meta, raw = row.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        name = raw.decode("utf-8")
        root_code = "/" not in name and PurePosixPath(name).suffix in CODE
        if _included(name) and (root_code or name in PUBLIC_SOURCES or any(name.startswith(scope + "/") for scope in SCOPES)):
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("unsupported_release_file")
            files[name] = oid
        if len(files) > MAX_ENTRIES:
            raise ValueError("release_inventory_limit")
    return files


def _read(root, name):
    """Pin each directory and reject symlinks, devices, and excessive content."""
    parts = PurePosixPath(name).parts
    if not parts or any(p in {"", ".", "..", "/"} for p in parts):
        raise ValueError("unsafe_release_path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(child, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_nlink != 1:
                raise ValueError("unsafe_release_file")
            data = handle.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("release_file_limit")
            return data
    finally:
        os.close(fd)


def _directory(root, name):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in PurePosixPath(name).parts:
            if part in {"..", "/"}:
                raise ValueError("unsafe_inventory_path")
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except (OSError, ValueError):
        os.close(fd)
        raise


def _walk(root, prefix="", *, private=True):
    """Inspect names only; never follow a directory link or enter private state."""
    pending, count = [prefix], [0]
    while pending:
        relative = pending.pop()
        path = root / relative
        if path.is_symlink():
            yield relative, True
            continue
        if not path.exists():
            continue
        fd = _directory(root, relative)
        try:
            yield from _entries(fd, relative, pending, private, count)
        finally:
            os.close(fd)


def _entries(fd, relative, pending, private, count):
    with os.scandir(fd) as entries:
        for entry in entries:
            count[0] += 1
            if count[0] > MAX_ENTRIES:
                raise ValueError("local_inventory_limit")
            name = (PurePosixPath(relative) / entry.name).as_posix()
            if private and not _included(name):
                continue
            if entry.is_symlink():
                yield name, True
            elif entry.is_dir(follow_symlinks=False):
                pending.append(name)
            else:
                yield name, False


def _problem(report, kind, name):
    report["finding_count"] += 1
    if len(report["findings"]) < 100:
        # Unknown filenames can contain private identifiers; report only a stable handle.
        report["findings"].append({"kind": kind, "path_id": hashlib.sha256(name.encode()).hexdigest()[:16]})


def _checkout(root, expected, previous, report):
    current, old = _tree(root, expected), _tree(root, previous)
    for name, oid in current.items():
        try:
            data = _read(root, name)
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != oid:
                _problem(report, "checkout_mismatch", name)
        except (OSError, ValueError):
            _problem(report, "checkout_unreadable", name)
    for scope in SCOPES:
        for name, link in _walk(root, scope):
            if name in current:
                continue
            if link or name in old or PurePosixPath(name).suffix in CODE:
                _problem(report, "unexpected_checkout_code", name)
            else:
                report["unmanaged_files"] += 1
    for count, entry in enumerate(root.iterdir(), 1):
        if count > MAX_ENTRIES:
            raise ValueError("root_inventory_limit")
        if entry.name not in current and entry.suffix in CODE and _included(entry.name):
            _problem(report, "unexpected_root_code", entry.name)
    report["checkout_files_checked"] = len(current)


def _installed(root, sha):
    data = _git(root, "show", f"{sha}:schemas/architecture_service_links.json")
    files = json.loads(data)["installed_files"]
    if not isinstance(files, dict) or len(files) > 100:
        raise ValueError("invalid_install_inventory")
    for destination, source in files.items():
        if not (destination.startswith("/usr/local/libexec/ladder-dragon/") or destination.startswith("/usr/local/bin/")):
            raise ValueError("invalid_install_destination")
        if not source.startswith("deploy/") or not _included(source) or not _included(destination.lstrip("/")):
            raise ValueError("invalid_install_source")
        if ".." in PurePosixPath(destination).parts or ".." in PurePosixPath(source).parts:
            raise ValueError("unsafe_install_path")
    return files


def _publication(root, expected, previous, web_root, installed_root, report):
    installed = _installed(root, expected)
    pairs = [(web_root, target, source) for source, target in DASHBOARD_ASSETS]
    pairs += [(installed_root, target.lstrip("/"), source) for target, source in installed.items()]
    for base, target, source in pairs:
        try:
            if _read(base, target) != _read(root, source):
                _problem(report, "installed_mismatch", target)
        except (OSError, ValueError):
            _problem(report, "installed_unreadable", target)
    allowed = {target for _, target in DASHBOARD_ASSETS}
    for name, _ in _walk(web_root, private=False):
        if name not in allowed:
            _problem(report, "unexpected_web_file", name)
    runtime_dir = "usr/local/libexec/ladder-dragon"
    for name, _ in _walk(installed_root, runtime_dir, private=False):
        if "/" + name not in installed:
            _problem(report, "unexpected_runtime_file", name)
    for removed in _installed(root, previous).keys() - installed.keys():
        if os.path.lexists(installed_root / removed.lstrip("/")):
            _problem(report, "retired_install_present", removed)
    report["installed_files_checked"] = len(pairs)


def audit(root, expected, previous, *, web_root=None, installed_root=Path("/")):
    report = {"schema_version": 1, "status": "PASS", "expected_sha": expected,
              "previous_sha": previous, "finding_count": 0, "findings": [], "unmanaged_files": 0,
              "excluded": ["private_state", "configuration", "venv", "python_caches", "rendered_system_configuration"],
              "deleted_files": 0}
    try:
        if _git(root, "rev-parse", "HEAD").decode().strip() != expected:
            raise ValueError("checkout_sha_mismatch")
        _tree(root, previous)
        _git(root, "merge-base", "--is-ancestor", previous, expected)
        _checkout(root, expected, previous, report)
        if web_root is not None:
            _publication(root, expected, previous, web_root, installed_root, report)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        _problem(report, "audit_incomplete", "audit")
    if report["finding_count"]:
        report["status"] = "BLOCKED"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--previous-sha", required=True)
    parser.add_argument("--web-root", type=Path)
    args = parser.parse_args(argv)
    report = audit(args.root, args.expected_sha, args.previous_sha, web_root=args.web_root)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
