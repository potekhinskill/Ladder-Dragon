#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: scan tracked files for credential leaks.
"""Fail fast when tracked source files contain high-confidence credentials."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from math import log2
from pathlib import Path


PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Telegram bot token": re.compile(r"(?<![A-Za-z0-9])\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
}
SECRET_ASSIGNMENT = re.compile(
    r"(?im)\b([A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD))\s*=\s*[\"']?"
    r"([A-Za-z0-9_./+=:-]{20,})"
)
PLACEHOLDER_WORDS = {"example", "placeholder", "replace", "changeme", "dummy", "test"}


def entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * log2(count / length) for count in counts.values())


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
        try:
            data = path.read_bytes()
        except OSError:
            continue
        # Decode with replacement after scanning the complete tracked byte stream.
        # This still catches credentials accidentally embedded in mostly-text files.
        text = data.decode("utf-8", errors="ignore")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path}: possible {label}")
        # Generic Binance and provider keys do not have a stable prefix. Check
        # high-entropy values only in credential-named assignments, while
        # allowing documented placeholders and test fixtures.
        if not (
            path.name.endswith(".example")
            or path.parts[0] in {"docs", "tests"}
            or path.suffix.lower() == ".md"
        ):
            for name, value in SECRET_ASSIGNMENT.findall(text):
                lowered = value.lower()
                if any(word in lowered for word in PLACEHOLDER_WORDS):
                    continue
                if entropy(value) >= 3.8:
                    findings.append(f"{path}: possible high-entropy {name}")
    if findings:
        print("\n".join(findings))
        return 1
    print("[OK] no tracked high-confidence secrets found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
