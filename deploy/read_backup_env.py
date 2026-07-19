#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate privileged backup settings without executing them as shell.
"""Validate the root-owned backup environment without shell evaluation."""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path


FIELDS = (
    "BACKUP_AGE_RECIPIENT",
    "BACKUP_EXTERNAL_MOUNT",
    "BACKUP_EXTERNAL_DIR",
    "BACKUP_EXTERNAL_RETENTION_DAYS",
)
PATH_RE = re.compile(r"^/[A-Za-z0-9._/@+-]+$")
AGE_RE = re.compile(r"^age1[0-9a-z]{20,}$")


def read_backup_env(path: Path, *, expected_uid: int = 0, expected_gid: int = 0) -> list[str]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError("backup.env must be a regular non-symlink file")
    if info.st_uid != expected_uid or info.st_gid != expected_gid:
        raise ValueError("backup.env must be owned by root:root")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("backup.env must have mode 0600")

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("backup.env contains a malformed line")
        name, value = line.split("=", 1)
        if name not in FIELDS or name in values:
            raise ValueError(f"backup.env contains forbidden or duplicate key: {name}")
        values[name] = value

    recipient = values.get("BACKUP_AGE_RECIPIENT", "")
    mount = values.get("BACKUP_EXTERNAL_MOUNT", "")
    directory = values.get("BACKUP_EXTERNAL_DIR", "")
    retention = values.get("BACKUP_EXTERNAL_RETENTION_DAYS", "90")
    if not AGE_RE.fullmatch(recipient):
        raise ValueError("BACKUP_AGE_RECIPIENT is invalid")
    if bool(mount) != bool(directory):
        raise ValueError("external mount and directory must be configured together")
    if mount:
        if not PATH_RE.fullmatch(mount) or not PATH_RE.fullmatch(directory):
            raise ValueError("external backup paths contain forbidden characters")
        if not directory.startswith(mount.rstrip("/") + "/"):
            raise ValueError("external backup directory must be below its mount")
    if not retention.isdigit() or int(retention) > 36500:
        raise ValueError("backup retention must be an integer between 0 and 36500")
    return [recipient, mount, directory, retention]


def main() -> int:
    try:
        values = read_backup_env(Path(sys.argv[1]))
    except (IndexError, OSError, ValueError) as exc:
        print(f"[SECURITY] {exc}", file=sys.stderr)
        return 2
    for value in values:
        sys.stdout.buffer.write(value.encode("utf-8") + b"\0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
