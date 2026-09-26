# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a Testnet soak boundary without changing monitoring behavior.
"""Testnet soak_parser implementation."""

from __future__ import annotations

import argparse
from decimal import Decimal
import os
from pathlib import Path
import re


def _parse_monitor_args():
    parser = argparse.ArgumentParser(
        description="Read-only invariant monitor for Binance Spot Testnet soak runs"
    )
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--duration-sec", type=int, default=43_200)
    parser.add_argument("--interval-sec", type=float, default=5.0)
    parser.add_argument("--max-open-buys", type=int, default=1)
    parser.add_argument(
        "--max-exposure-usdt",
        type=Decimal,
        default=Decimal(os.getenv("RISK_PORTFOLIO_CAP_USDT", "25")),
    )
    parser.add_argument("--grace-sec", type=float, default=10.0)
    parser.add_argument("--max-consecutive-read-failures", type=int, default=12)
    parser.add_argument(
        "--report",
        default=str(Path(os.environ["BOT_RUN_DIR"]) / "soak_report.json"),
    )
    args = parser.parse_args()
    symbol = args.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol):
        parser.error("--symbol must be a valid uppercase Binance symbol")
    if args.duration_sec < 0 or args.interval_sec <= 0 or args.grace_sec < 0:
        parser.error("duration/grace must be non-negative and interval must be > 0")
    if args.max_open_buys < 0 or args.max_exposure_usdt <= 0:
        parser.error("BUY count must be non-negative and exposure must be > 0")
    if args.max_consecutive_read_failures <= 0:
        parser.error("--max-consecutive-read-failures must be > 0")
    return parser, args, symbol
