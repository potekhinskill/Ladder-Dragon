#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: audit legacy compatibility before a future major-version removal.
"""Print a read-only legacy compatibility retirement report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ladder_dragon.execution.compatibility_audit import audit_compatibility


DEFAULT_LEGACY_PATHS = (
    Path("/etc/bot-alerts.env"),
    Path("/etc/systemd/system/pi-dashboard.service"),
    Path("/etc/systemd/system/ai-supervisor.service"),
    Path("/etc/systemd/system/binance-bot.service"),
    Path("/etc/nginx/sites-available/pi-dashboard"),
    Path("/etc/nginx/sites-enabled/pi-dashboard"),
    Path("/opt/pi-dashboard"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats-db", type=Path, required=True)
    parser.add_argument(
        "--legacy-path",
        action="append",
        type=Path,
        default=None,
        help="override the legacy paths checked by the audit",
    )
    args = parser.parse_args()
    report = audit_compatibility(
        args.stats_db,
        legacy_paths=(
            tuple(args.legacy_path)
            if args.legacy_path is not None
            else DEFAULT_LEGACY_PATHS
        ),
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready_for_major_removal else 2


if __name__ == "__main__":
    raise SystemExit(main())
