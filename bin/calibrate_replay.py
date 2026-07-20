#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: calibrate deterministic replay parameters from archived Binance events.
"""Create an auditable replay calibration report from a JSONL archive."""

from __future__ import annotations

import argparse
import json

from ladder_dragon.strategy.market_replay import (
    archive_sha256,
    calibrate_market_events,
    load_jsonl_archive,
    write_calibration,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", help="Binance snapshot/depth/trade JSONL")
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-book-events", type=int, default=100)
    parser.add_argument("--min-trades", type=int, default=50)
    args = parser.parse_args()
    if args.min_book_events < 1 or args.min_trades < 1:
        parser.error("minimum sample counts must be positive")
    events = load_jsonl_archive(args.archive)
    report = calibrate_market_events(
        events,
        source_sha256=archive_sha256(args.archive),
        min_book_events=args.min_book_events,
        min_trades=args.min_trades,
    )
    write_calibration(args.output, report)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
