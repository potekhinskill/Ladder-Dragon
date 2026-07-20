#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: record public Binance Spot depth and aggregate trades for replay.
"""Create a public-only, source-hashed Binance Spot replay archive."""

import argparse
import json

import requests
from websocket import WebSocketException

from ladder_dragon.strategy.depth_archive import record_public_depth


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-sec", type=int, default=300)
    parser.add_argument("--max-events", type=int, default=100_000)
    parser.add_argument("--depth-limit", type=int, default=1000)
    args = parser.parse_args()
    try:
        result = record_public_depth(
            args.symbol,
            args.output,
            duration_sec=args.duration_sec,
            max_events=args.max_events,
            depth_limit=args.depth_limit,
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        requests.RequestException,
        WebSocketException,
    ) as exc:
        parser.error(f"archive recording failed: {type(exc).__name__}: {exc}")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
