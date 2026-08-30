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
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
from ladder_dragon.strategy.prediction.v23_confirmation_planner import (
    plan_v23_confirmation_drafts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-directory", required=True, type=Path)
    parser.add_argument("--draft-directory", required=True, type=Path)
    parser.add_argument("--context-db", required=True, type=Path)
    parser.add_argument("--prediction-db", type=Path)
    args = parser.parse_args()
    try:
        report = plan_replay_drafts(
            args.archive_directory, args.draft_directory, args.context_db
        )
        atomic_json(args.draft_directory / "status.json", report, replace=True)
        confirmation = None
        if args.prediction_db is not None and args.prediction_db.is_file():
            confirmation_directory = (
                args.draft_directory.parent / "confirmation-drafts"
            )
            confirmation = plan_v23_confirmation_drafts(
                PredictionShadowStore(args.prediction_db),
                args.archive_directory,
                confirmation_directory,
                args.context_db,
            )
            atomic_json(
                confirmation_directory / "status.json",
                confirmation,
                replace=True,
            )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        blocked = {
            "schema_version": 3,
            "mode": "SHADOW",
            "apply_allowed": False,
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "draft_count": 0,
        }
        atomic_json(
            args.draft_directory / "status.json", blocked, replace=True
        )
        print(f"[HISTORICAL-PLANNER] status=BLOCKED error={type(exc).__name__}")
        return 2
    print(
        f"[HISTORICAL-PLANNER] status={report['status']} "
        f"drafts={report['draft_count']}"
    )
    if confirmation is not None:
        print(
            f"[V23-CONFIRMATION-PLANNER] status={confirmation['status']} "
            f"drafts={confirmation['draft_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
