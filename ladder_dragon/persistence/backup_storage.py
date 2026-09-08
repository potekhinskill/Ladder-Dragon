# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify availability of status-bound external encrypted backups.
"""Check external artifact availability without decrypting recovery data."""

from __future__ import annotations

import os
import re
from pathlib import Path


def external_archive_available(status: dict[str, object]) -> bool:
    """Require the mounted store and exact producer-verified artifact identity."""
    try:
        if status.get("storage") != "external" or status.get("archive_verified") is not True:
            return False
        name, digest, size = (status.get(key) for key in (
            "archive_name", "archive_sha256", "archive_size_bytes"
        ))
        if (
            not isinstance(name, str)
            or re.fullmatch(r"ladder-dragon-\d{4}-\d{2}-\d{2}-\d{6}\.tgz\.age", name) is None
            or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int or size <= 0
        ):
            return False
        mount = Path(str(status["external_mount"]))
        directory = Path(str(status["external_directory"]))
        if (
            not mount.is_absolute() or not directory.is_absolute()
            or mount.resolve(strict=True) != mount
            or directory.resolve(strict=True) != directory
            or not os.path.ismount(mount)
            or mount not in directory.parents
            or mount.stat().st_dev == Path("/").stat().st_dev
            or directory.stat().st_dev != mount.stat().st_dev
        ):
            return False
        archive, checksum = directory / name, directory / (name + ".sha256")
        if (
            archive.is_symlink() or checksum.is_symlink()
            or not archive.is_file() or not checksum.is_file()
            or archive.stat().st_size != size or checksum.stat().st_size > 256
        ):
            return False
        return checksum.read_text(encoding="ascii").split() == [digest, name]
    except (KeyError, OSError, RuntimeError, UnicodeError, ValueError):
        return False
