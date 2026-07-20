#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: explicitly retire SQLite REAL accounting columns for a major release.
"""Preview or apply the backed-up exact-only accounting migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ladder_dragon.execution.accounting_retirement import retire_accounting_schema
from ladder_dragon.execution.compatibility_audit import (
    DEFAULT_LEGACY_PATHS,
    audit_compatibility,
)


CONFIRMATION = "DROP-LEGACY-REAL-COLUMNS"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats-db", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    report = audit_compatibility(
        args.stats_db, legacy_paths=DEFAULT_LEGACY_PATHS
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    if not args.apply:
        return 0 if report.ready_for_major_removal else 2
    if args.confirm != CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {CONFIRMATION}")
    if args.backup is None:
        raise SystemExit("--apply requires --backup outside the live database path")
    changed = retire_accounting_schema(args.stats_db, args.backup)
    print("Retired legacy REAL accounting columns." if changed else "Already exact-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
