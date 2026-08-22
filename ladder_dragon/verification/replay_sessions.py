# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate execution outcomes across separate contiguous depth sessions.
"""Build one replay artifact without joining gaps between public archives."""

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
    ReplayValidationSession,
    validate_replay_sessions,
    write_replay_validation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session",
        nargs=2,
        action="append",
        metavar=("ARCHIVE", "CALIBRATION"),
        required=True,
    )
    parser.add_argument("--execution-log", required=True)
    parser.add_argument("--output")
    parser.add_argument("--minimum-orders", type=int, default=10)
    for name, value in (
        ("minimum-classification-accuracy", "0.80"),
        ("maximum-fill-ratio-mae", "0.25"),
        ("maximum-price-error-bps-mae", "10"),
        ("maximum-latency-error-ms-mae", "1000"),
        ("maximum-fee-error-quote-mae", "0.02"),
        ("maximum-slippage-error-bps-mae", "10"),
    ):
        parser.add_argument(f"--{name}", type=Decimal, default=Decimal(value))
    for name in (
        "maker-buy-fee-pct",
        "maker-sell-fee-pct",
        "taker-buy-fee-pct",
        "taker-sell-fee-pct",
    ):
        parser.add_argument(f"--{name}", type=Decimal, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sessions = [
        ReplayValidationSession(
            events=tuple(load_jsonl_archive(archive)),
            calibration=read_calibration(calibration),
        )
        for archive, calibration in args.session
    ]
    report = validate_replay_sessions(
        sessions,
        load_execution_outcomes(args.execution_log),
        minimum_orders=args.minimum_orders,
        minimum_classification_accuracy=args.minimum_classification_accuracy,
        maximum_fill_ratio_mae=args.maximum_fill_ratio_mae,
        maximum_price_error_bps_mae=args.maximum_price_error_bps_mae,
        maximum_latency_error_ms_mae=args.maximum_latency_error_ms_mae,
        maximum_fee_error_quote_mae=args.maximum_fee_error_quote_mae,
        maximum_slippage_error_bps_mae=args.maximum_slippage_error_bps_mae,
        maker_buy_fee_pct=args.maker_buy_fee_pct,
        maker_sell_fee_pct=args.maker_sell_fee_pct,
        taker_buy_fee_pct=args.taker_buy_fee_pct,
        taker_sell_fee_pct=args.taker_sell_fee_pct,
    )
    if args.output:
        write_replay_validation(args.output, report)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


__all__ = ["build_parser", "main"]
