# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: check current project documentation against its English profile.
"""Check current project documentation against the English writing profile."""

from __future__ import annotations

from pathlib import Path

from ladder_dragon.verification.technical_english import check_documents


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    issues = check_documents(root)
    for issue in issues:
        print(issue.format())
    if issues:
        print(f"Technical English check: FAILED ({len(issues)} issues)")
        return 1
    print("Technical English check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
