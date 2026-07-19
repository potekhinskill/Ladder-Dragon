#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: parse the root-owned update trust anchor without executing it.
"""Read the one-field update trust configuration as untrusted text."""

from __future__ import annotations

import re
import sys
from pathlib import Path


LINE = re.compile(r"TRUSTED_GPG_FINGERPRINT=([0-9A-Fa-f]{40,64})")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: read_update_trust.py PATH", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    values: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE.fullmatch(line)
        if not match:
            print(f"invalid update trust configuration at line {number}", file=sys.stderr)
            return 2
        values.append(match.group(1).upper())
    if len(values) != 1:
        print("update trust configuration must define exactly one fingerprint", file=sys.stderr)
        return 2
    print(values[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
