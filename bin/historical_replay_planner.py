#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: create review-only historical replay requests.
"""Plan deterministic historical entry replay blocks without queueing them."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from ladder_dragon.strategy.depth_segments import atomic_json
from ladder_dragon.strategy.prediction.historical_replay_planner import (
    plan_replay_drafts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-directory", required=True, type=Path)
    parser.add_argument("--draft-directory", required=True, type=Path)
    parser.add_argument("--context-db", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = plan_replay_drafts(
            args.archive_directory, args.draft_directory, args.context_db
        )
        atomic_json(args.draft_directory / "status.json", report, replace=True)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f"[HISTORICAL-PLANNER] status=BLOCKED error={type(exc).__name__}")
        return 2
    print(
        f"[HISTORICAL-PLANNER] status={report['status']} "
        f"drafts={report['draft_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
