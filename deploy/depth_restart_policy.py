#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: decide whether one verified update must restart public depth capture.
"""Fail-closed release policy for preserving a continuous depth session."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable


PRESERVABLE_FILES = frozenset(
    {
        "CHANGELOG.md",
        "DECISIONS.md",
        "MISTAKES.md",
        "README.md",
        "product_version.py",
    }
)
PRESERVABLE_PREFIXES = (
    "FastAPI/pi-dashboard/",
    "FRONT/",
    "docs/",
    "ladder_dragon/dashboard/",
    "ladder_dragon/deployment/",
    "ladder_dragon/supervision/",
    "tests/",
)


def depth_restart_required(changed_paths: Iterable[str]) -> bool:
    """Require restart unless every changed path has a reviewed safe scope."""
    paths = tuple(changed_paths)
    if not paths:
        return True
    for path in paths:
        if not path or path.startswith("/") or "\x00" in path:
            return True
        if path in PRESERVABLE_FILES:
            continue
        if path.startswith(PRESERVABLE_PREFIXES):
            continue
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--null", action="store_true")
    args = parser.parse_args()
    raw = sys.stdin.buffer.read()
    separator = b"\0" if args.null else b"\n"
    paths = [os.fsdecode(item) for item in raw.split(separator) if item]
    print("restart" if depth_restart_required(paths) else "preserve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
