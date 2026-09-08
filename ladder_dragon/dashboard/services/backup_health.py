# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate sanitized encrypted-backup evidence for the dashboard.
"""Fail-closed dashboard validation for encrypted backup evidence."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from ladder_dragon.persistence.backup_storage import external_archive_available


ARCHIVE_NAME = re.compile(
    r"ladder-dragon-\d{4}-\d{2}-\d{2}-\d{6}\.tgz\.age"
)
SHA256 = re.compile(r"[0-9a-f]{64}")
STATUS_SCHEMA_VERSION = 2


def _external_links_valid(public_dir: Path, status: dict[str, object], name: str) -> bool:
    """Reject detached storage and pointers outside the status-bound store."""
    if "storage" not in status:
        return True  # Legacy local archives remain readable during deployment.
    if not external_archive_available(status):
        return False
    try:
        directory = Path(str(status["external_directory"]))
        for suffix in ("", ".sha256"):
            link = public_dir / (name + suffix)
            target = directory / (name + suffix)
            if not link.is_symlink() or link.readlink() != target:
                return False
            if target.is_symlink() or not target.is_file():
                return False
        return True
    except (KeyError, OSError, RuntimeError, ValueError):
        return False


def _unknown(public_dir: Path, reason: str, archive_count: int) -> dict[str, object]:
    return {
        "status": "unknown",
        "reason": reason,
        "directory": str(public_dir),
        "archive_count": archive_count,
    }


def _read_status(paths: tuple[Path, ...]) -> dict[str, object] | None:
    candidates: list[tuple[float, dict[str, object]]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            modified = path.stat().st_mtime
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == STATUS_SCHEMA_VERSION
            and payload.get("status") in {"success", "failed"}
        ):
            candidates.append((modified, payload))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def backup_snapshot(
    *,
    public_dir: Path,
    status_paths: tuple[Path, ...],
    timezone,
    minimum_archive_bytes: int = 1024,
    now: Callable[[], float] = time.time,
) -> dict[str, object]:
    """Return success only for one status-bound encrypted archive."""
    minimum_size = max(1, int(minimum_archive_bytes))
    try:
        archives = sorted(
            public_dir.glob("ladder-dragon-*.tgz.age"),
            key=lambda path: path.stat().st_mtime,
        )
    except OSError:
        return {
            "status": "unavailable",
            "reason": "backup directory is not readable",
            "directory": str(public_dir),
        }
    archive_count = len(archives)
    status = _read_status(status_paths)
    if status is None:
        return _unknown(public_dir, "verified backup status is unavailable", archive_count)
    if status["status"] == "failed":
        return {
            "status": "failed",
            "reason": str(status.get("reason") or "backup failed"),
            "directory": str(public_dir),
            "archive_count": archive_count,
        }
    name = status.get("archive_name")
    digest = status.get("archive_sha256")
    size = status.get("archive_size_bytes")
    if (
        not isinstance(name, str)
        or ARCHIVE_NAME.fullmatch(name) is None
        or not isinstance(digest, str)
        or SHA256.fullmatch(digest) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or status.get("archive_verified") is not True
    ):
        return _unknown(public_dir, "verified backup identity is invalid", archive_count)
    archive = public_dir / name
    checksum = public_dir / f"{name}.sha256"
    if not _external_links_valid(public_dir, status, name):
        return _unknown(public_dir, "external backup storage is unavailable", archive_count)
    try:
        if not archive.is_file() or not checksum.is_file() or checksum.stat().st_size > 256:
            return _unknown(public_dir, "verified backup files are unavailable", archive_count)
        stat = archive.stat()
        checksum_fields = checksum.read_text(encoding="ascii").strip().split()
    except (OSError, UnicodeError):
        return _unknown(public_dir, "verified backup files are unavailable", archive_count)
    if size < minimum_size or stat.st_size < minimum_size:
        return _unknown(public_dir, "archive is suspiciously small", archive_count)
    if stat.st_size != size:
        return _unknown(public_dir, "archive size differs from backup status", archive_count)
    if checksum_fields != [digest, name]:
        return _unknown(public_dir, "archive checksum evidence differs", archive_count)
    if archives and archives[-1].name != name:
        return _unknown(public_dir, "a newer unverified archive exists", archive_count)
    return {
        "status": "success",
        "reason": None,
        "directory": str(public_dir),
        "last_success": {
            "name": name,
            "size_bytes": stat.st_size,
            "sha256": digest,
            "age_sec": max(0, int(now() - stat.st_mtime)),
            "updated_at": datetime.fromtimestamp(
                stat.st_mtime, timezone
            ).strftime("%Y-%m-%d %H:%M:%S"),
        },
        "archive_count": archive_count,
    }


__all__ = ["backup_snapshot"]
