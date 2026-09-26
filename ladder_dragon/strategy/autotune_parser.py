# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a VWAP autotune boundary with unchanged tuning behavior.
"""VWAP autotune_parser implementation."""

from __future__ import annotations

import argparse
from decimal import Decimal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--pnl-threshold", type=Decimal, default=Decimal("25.0"),
                        help="USDT PnL threshold to adjust more aggressively")
    parser.add_argument("--min-trades", type=int, default=20,
                        help="Minimum recent executions before tuning")
    parser.add_argument("--alpha", type=float, default=0.6,
                        help="EMA smoothing for new values")
    parser.add_argument("--precision", type=int, default=6)

    parser.add_argument("--base-premium", type=float, default=0.0030)
    parser.add_argument("--base-discount", type=Decimal, default=Decimal("0.0060"))
    parser.add_argument("--base-scale", type=float, default=1.30)

    parser.add_argument("--premium-loss-mult", type=float, default=1.20)
    parser.add_argument("--premium-profit-mult", type=float, default=0.80)
    parser.add_argument("--premium-floor", type=float, default=0.0005)
    parser.add_argument("--premium-ceil", type=float, default=0.0100)

    parser.add_argument("--scale-loss-mult", type=float, default=0.80)
    parser.add_argument("--scale-profit-mult", type=float, default=1.20)
    parser.add_argument("--scale-min", type=float, default=0.8)
    parser.add_argument("--scale-max", type=float, default=3.0)

    parser.add_argument("--discount-min", type=Decimal, default=Decimal("0"))
    parser.add_argument("--discount-max", type=Decimal, default=Decimal("0.0200"))
    parser.add_argument("--discount-loss-mult", type=Decimal, default=Decimal("1.20"))
    parser.add_argument("--discount-profit-mult", type=Decimal, default=Decimal("0.80"))

    parser.add_argument("--state-file", type=str, default=None,
                        help="JSON file to store previous tuned values (optional)")
    parser.add_argument("--stats-db", type=str, default=None,
                        help="Path to SQLite stats DB (defaults to TS.BOT_STATS_DB or env)")

    return parser
