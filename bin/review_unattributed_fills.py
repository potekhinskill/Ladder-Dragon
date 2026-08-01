#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: review historical AI attribution gaps without inventing decision links.

"""Review journal-proven attribution gaps while preserving all raw evidence."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3

from ladder_dragon.ai.context.decision_repository import AdvisorDecisionStore
from ladder_dragon.ai.unresolved_fills import lifecycle_counts
from ladder_dragon.ai.unresolved_review import REVIEW_NOTES, review_unattributable_fills


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mark journal-proven historical fills as reviewed and unattributable."
    )
    parser.add_argument("--ai-db", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument(
        "--note", required=True, choices=sorted(REVIEW_NOTES)
    )
    parser.add_argument("--before-ts", required=True, type=int)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    ai_path = Path(args.ai_db)
    with sqlite3.connect(
        f"file:{ai_path}?mode=ro", uri=True, timeout=5
    ) as connection:
        before = lifecycle_counts(connection)
    candidates = review_unattributable_fills(
        args.ai_db,
        args.journal,
        note=args.note,
        before_ts=args.before_ts,
        expected_count=args.expected_count,
    )
    if not args.apply:
        print(
            "Review preview: "
            f"candidates={candidates} pending={before['pending']} "
            f"reviewed={before['reviewed_unattributable']}"
        )
        return 0
    if os.getenv("BOT_UNATTRIBUTED_REVIEW_CONFIRMED") != "YES":
        raise RuntimeError("BOT_UNATTRIBUTED_REVIEW_CONFIRMED=YES is required")
    store = AdvisorDecisionStore(args.ai_db)
    reviewed = review_unattributable_fills(
        args.ai_db,
        args.journal,
        note=args.note,
        before_ts=args.before_ts,
        expected_count=args.expected_count,
        apply=True,
    )
    after = store.unresolved_fill_lifecycle_counts()
    print(
        "Review applied: "
        f"reviewed_now={reviewed} pending={after['pending']} "
        f"reviewed_total={after['reviewed_unattributable']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
