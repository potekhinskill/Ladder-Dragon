#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: audit whether replay calibration has enough empirical coverage.
"""Audit several replay calibration reports without accessing exchange keys."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json

from ladder_dragon.strategy.market_replay import read_calibration
from ladder_dragon.strategy.replay_readiness import audit_replay_readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("calibrations", nargs="+")
    parser.add_argument("--minimum-archives", type=int, default=3)
    parser.add_argument("--minimum-span-days", type=Decimal, default=Decimal("2"))
    parser.add_argument("--minimum-measured-latency-archives", type=int, default=1)
    parser.add_argument("--minimum-execution-samples", type=int, default=10)
    parser.add_argument("--low-max-bps", type=Decimal, default=Decimal("0.5"))
    parser.add_argument("--high-min-bps", type=Decimal, default=Decimal("2"))
    args = parser.parse_args()
    report = audit_replay_readiness(
        [read_calibration(path) for path in args.calibrations],
        minimum_archives=args.minimum_archives,
        minimum_span_days=args.minimum_span_days,
        minimum_measured_latency_archives=args.minimum_measured_latency_archives,
        minimum_execution_samples=args.minimum_execution_samples,
        low_max_bps=args.low_max_bps,
        high_min_bps=args.high_min_bps,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
