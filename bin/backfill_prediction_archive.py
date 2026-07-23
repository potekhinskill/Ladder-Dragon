#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: recover expired SHADOW outcomes from verified public archives.
"""Backfill INSUFFICIENT_HISTORY outcomes without changing trading decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ladder_dragon.strategy.prediction import PredictionShadowStore
from ladder_dragon.strategy.prediction_archive import (
    load_verified_prediction_archive,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--as-of-ms", type=int)
    args = parser.parse_args(argv)
    source = load_verified_prediction_archive(args.archive)
    recovered = PredictionShadowStore(args.database).backfill_expired(
        source.symbol,
        source.bars,
        source_sha256=source.source_sha256,
        as_of_ms=args.as_of_ms,
    )
    print(json.dumps({
        "symbol": source.symbol,
        "source_sha256": source.source_sha256,
        "recovered": recovered,
        "trading_changes": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
