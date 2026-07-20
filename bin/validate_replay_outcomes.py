#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate replay predictions against sanitized execution reports.
"""Produce a fail-closed empirical replay validation report."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json

from ladder_dragon.execution.execution_latency import load_execution_outcomes
from ladder_dragon.strategy.market_replay import (
    load_jsonl_archive,
    read_calibration,
)
from ladder_dragon.strategy.replay_validation import (
    validate_replay_outcomes,
    write_replay_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--execution-log", required=True)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--output")
    parser.add_argument("--minimum-orders", type=int, default=10)
    parser.add_argument(
        "--minimum-classification-accuracy",
        type=Decimal,
        default=Decimal("0.80"),
    )
    parser.add_argument(
        "--maximum-fill-ratio-mae", type=Decimal, default=Decimal("0.25")
    )
    parser.add_argument(
        "--maximum-price-error-bps-mae",
        type=Decimal,
        default=Decimal("10"),
    )
    parser.add_argument(
        "--maximum-latency-error-ms-mae",
        type=Decimal,
        default=Decimal("1000"),
    )
    args = parser.parse_args()
    report = validate_replay_outcomes(
        load_jsonl_archive(args.archive),
        load_execution_outcomes(args.execution_log),
        read_calibration(args.calibration),
        minimum_orders=args.minimum_orders,
        minimum_classification_accuracy=(
            args.minimum_classification_accuracy
        ),
        maximum_fill_ratio_mae=args.maximum_fill_ratio_mae,
        maximum_price_error_bps_mae=args.maximum_price_error_bps_mae,
        maximum_latency_error_ms_mae=args.maximum_latency_error_ms_mae,
    )
    rendered = json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        write_replay_validation(args.output, report)
    print(rendered, end="")
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
