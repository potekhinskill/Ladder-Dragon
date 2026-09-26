# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own reviewed experiment CLI responsibilities.
from __future__ import annotations

import subprocess
from product_version import __version__


def _source_commit() -> str:
    """Return one clean, published, annotated release checkout identity."""
    def git_output(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    try:
        value = git_output("rev-parse", "HEAD").lower()
        if git_output("status", "--porcelain"):
            raise RuntimeError("CHAMPION activation requires a clean checkout")
        tag = f"v{__version__}"
        if git_output("cat-file", "-t", f"refs/tags/{tag}") != "tag":
            raise RuntimeError("CHAMPION activation requires an annotated release tag")
        if git_output("rev-list", "-n", "1", tag).lower() != value:
            raise RuntimeError("CHAMPION activation release tag differs from HEAD")
        if git_output("rev-parse", "origin/main").lower() != value:
            raise RuntimeError("CHAMPION activation requires the published main release")
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("source commit is unavailable") from exc
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError("source commit is invalid")
    return value
