#!/usr/bin/env python3
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: scan tracked files for credential leaks.
"""Minimal fail-fast secret scan for tracked repository files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}
IGNORED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".db", ".sqlite3"}


def main() -> int:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    findings: list[str] = []
    for raw in tracked:
        if not raw:
            continue
        path = Path(raw.decode())
        if path.suffix.lower() in IGNORED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path}: possible {label}")
    if findings:
        print("\n".join(findings))
        return 1
    print("[OK] no tracked high-confidence secrets found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
