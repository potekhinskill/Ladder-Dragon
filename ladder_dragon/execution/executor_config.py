# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor config component of the execution layer.
"""Ladder Dragon executor config support."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from product_version import product_label


def build_executor_parser() -> argparse.ArgumentParser:
    """Build executor parser."""
    parser = argparse.ArgumentParser(description="Ladder Dragon symbol executor")
    parser.add_argument("--version", action="version", version=product_label("executor"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--ladder-prices", required=True, help="comma-separated absolute prices")
    parser.add_argument("--max-oco-per-symbol", type=int, default=None)
    parser.add_argument("--tp1", type=float, default=0.08)
    parser.add_argument("--tp2", type=float, default=0.08)
    parser.add_argument("--sl", type=float, default=-0.01)
    parser.add_argument("--status-interval", type=int, default=5)
    parser.add_argument("--loop-minutes", type=int, default=5)
    parser.add_argument("--oco-fallback", type=str, choices=("halt", "prefer-tp1"), default="halt")
    parser.add_argument("--max-holding-minutes", type=int, default=0,
                        help="LIVE time-stop; 0 disables the additional guard")
    parser.add_argument("--target-buy-per-symbol", type=int, default=10)
    parser.add_argument("--auto-oco-holdings", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--enforce-target-buys", action="store_true")
    parser.add_argument("--enforce-sell-limit", action="store_true")

    # New flags (BUY gates)
    parser.add_argument("--cap-floor-usdt", type=float, default=None,
                        help="Do not place BUY orders when free USDT is below this threshold")
    parser.add_argument("--min-order-usdt", type=float, default=None,
                        help="Do not place a BUY when its notional is below this USDT threshold")

    # Patch: attach OCO automatically after a BUY fill
    parser.add_argument("--attach-oco-on-fill", action="store_true",
                        help="Automatically attach an OCO TP/SL SELL after a BUY is filled")
    parser.add_argument("--stop-limit-offset-pct", type=float, default=0.0015,
                        help="Offset the SELL stop-limit price below its stop price by this fraction")
    parser.add_argument("--check-fills-interval", type=int, default=5,
                        help="BUY status polling interval in seconds while waiting to attach OCO")

    # Dynamic CAP controls
    parser.add_argument("--use-remainder-in-last", action="store_true",
                        help="Allow the final BUY to use all remaining USDT; otherwise allocate evenly")

    # New flags: breakeven after TP1 (optional, per symbol)
    parser.add_argument("--breakeven-on-tp1-symbols", type=str, default="",
                        help="Enable a breakeven stop after partial TP1 for the comma-separated symbols")
    parser.add_argument("--breakeven-offset-pct", type=float, default=None,
                        help="Breakeven offset above average entry; defaults to 2*BOT_FEE_PCT")
    parser.add_argument("--breakeven-check-interval", type=int, default=5,
                        help="How often to inspect OCO for partial TP fills, in one-second loop steps")

    # Panic and indicators
    parser.add_argument("--panic-drop-pct", type=float, default=0.02,
                        help="Drop from previous close that triggers panic mode (fraction; 0.02 means -2%%)")
    parser.add_argument("--panic-k-atr",   type=float, default=2.0,
                        help="EMA20 minus k*ATR threshold that triggers panic mode")
    parser.add_argument("--panic-debounce-checks", type=int, default=2,
                        help="Number of consecutive confirmations required to enter panic mode")
    parser.add_argument("--panic-cooldown-sec",    type=int, default=180,
                        help="Minimum panic-mode hold time before exit")
    parser.add_argument("--panic-interval", type=str, default="1m",
                        help="Timeframe for panic indicators, for example 1m or 5m")
    parser.add_argument("--panic-sell-floor-pct", type=float, default=None,
                        help="In panic mode, do not sell below average entry * (1 - pct); unset means no floor")
    parser.add_argument("--avg-lookback", type=int, default=1000,
                        help="Number of recent trades used to calculate average entry")
    parser.add_argument("--avg-cache-ttl", type=int, default=30,
                        help="Position average-entry cache TTL in seconds")
    parser.add_argument("--sell-limit-maker", action="store_true",
                        help="Place holdings SELL orders as maker-only LIMIT_MAKER orders")
    parser.add_argument("--buy-limit-maker", action="store_true",
                        help="Place BUY orders as maker-only LIMIT_MAKER orders")

    # Trend and bearish filters
    parser.add_argument("--skip-buy-while-panic", action="store_true",
                        help="Do not place new BUY orders while panic mode is active")
    parser.add_argument("--buy-trend-ema-gap", type=float, default=None,
                        help="Treat the market as bearish when price is this fraction below EMA")
    parser.add_argument("--buy-trend-interval", type=str, default=None,
                        help="EMA interval for the trend filter; defaults to panic-interval")
    parser.add_argument("--bear-skip-buys", action="store_true",
                        help="Skip all new BUY orders when the bearish trend signal is active")
    parser.add_argument("--bear-cap-scale", type=float, default=1.0,
                        help="Per-order CAP multiplier under a bearish signal (1.0 leaves it unchanged)")
    parser.add_argument("--bear-buy-shift-pct", type=float, default=0.0,
                        help="Shift BUY levels down by this fraction under a bearish signal")
    parser.add_argument("--buy-vwap-premium", type=float, default=None,
                        help="Skip BUY when price exceeds VWAP by this fraction")
    parser.add_argument("--buy-vwap-discount", type=float, default=None,
                        help="Increase CAP when price is this fraction below VWAP")
    parser.add_argument("--buy-vwap-discount-scale", type=float, default=1.0,
                        help="CAP multiplier when price trades below VWAP")
    parser.add_argument("--buy-vwap-interval", type=str, default="1m",
                        help="Candle interval used to calculate VWAP")
    parser.add_argument("--buy-vwap-window", type=int, default=180,
                        help="Number of closed candles used to calculate VWAP")

    return parser
def validate_executor_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> argparse.Namespace:
    """Validate executor args."""
    # --live alone is insufficient: the operator must explicitly confirm
    # mutations through the environment of this process.
    if args.live and os.getenv("BOT_LIVE_CONFIRMED", "") != "YES":
        parser.error("--live requires BOT_LIVE_CONFIRMED=YES")
    lock_file = os.getenv("BOT_PARAM_LOCK_FILE", "").strip()
    if args.live and lock_file and Path(lock_file).exists():
        parser.error("LIVE is blocked because walk-forward validation marked the parameters as degraded")
    if args.live and args.oco_fallback == "prefer-tp1":
        parser.error("--oco-fallback=prefer-tp1 is forbidden in LIVE because it leaves the position without a stop")
    if args.max_holding_minutes < 0:
        parser.error("--max-holding-minutes must be >= 0")
    args.symbol = args.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol):
        parser.error("--symbol must be a valid uppercase Binance symbol")
    if args.target_buy_per_symbol <= 0 or args.loop_minutes <= 0:
        parser.error("target and loop limits must be > 0")
    if args.cap_floor_usdt is not None and args.cap_floor_usdt < 0:
        parser.error("--cap-floor-usdt must be >= 0")
    if args.min_order_usdt is not None and args.min_order_usdt <= 0:
        parser.error("--min-order-usdt must be > 0")
    if not 0 <= args.stop_limit_offset_pct < 0.25:
        parser.error("--stop-limit-offset-pct must be in [0, 0.25)")
    return args
