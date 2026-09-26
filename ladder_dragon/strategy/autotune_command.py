# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a VWAP autotune boundary with unchanged tuning behavior.
"""VWAP autotune_command implementation."""

from __future__ import annotations

import os
import sqlite3
import sys
from decimal import Decimal
from typing import Dict

from ladder_dragon.persistence.migrations import migrate
from ladder_dragon.strategy.autotune_math import clamp, fmt_map, ema, adaptive_discount, decimal_ema
from ladder_dragon.strategy.autotune_history import get_stats
from ladder_dragon.strategy.autotune_state import load_prev_values, save_values
from ladder_dragon.strategy.autotune_parser import build_parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        adaptive_discount(
            args.base_discount,
            pnl=0,
            trade_count=0,
            minimum_trades=args.min_trades,
            pnl_threshold=args.pnl_threshold,
            loss_multiplier=args.discount_loss_mult,
            profit_multiplier=args.discount_profit_mult,
            minimum=args.discount_min,
            maximum=args.discount_max,
        )
        decimal_ema(None, args.base_discount, args.alpha)
    except ValueError as exc:
        parser.error(str(exc))

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("# VWAP autotune: no symbols", file=sys.stderr)
        sys.exit(1)

    stats_db = args.stats_db or os.getenv("BOT_STATS_DB")
    if not stats_db:
        print("# VWAP autotune: no stats DB (set BOT_STATS_DB)", file=sys.stderr)
        sys.exit(1)

    migrate(stats_db)
    conn = sqlite3.connect(stats_db)
    prev_values = load_prev_values(args.state_file)

    premium_map: Dict[str, float] = {}
    discount_map: Dict[str, Decimal] = {}
    scale_map: Dict[str, float] = {}

    for symbol in symbols:
        pnl, trade_cnt = get_stats(symbol, conn, args.hours)

        base_premium = prev_values.get(symbol, {}).get("premium", args.base_premium)
        base_discount = prev_values.get(symbol, {}).get("discount", args.base_discount)
        base_scale = prev_values.get(symbol, {}).get("scale", args.base_scale)

        premium = base_premium
        discount = adaptive_discount(
            base_discount,
            pnl=pnl,
            trade_count=trade_cnt,
            minimum_trades=args.min_trades,
            pnl_threshold=args.pnl_threshold,
            loss_multiplier=args.discount_loss_mult,
            profit_multiplier=args.discount_profit_mult,
            minimum=args.discount_min,
            maximum=args.discount_max,
        )
        scale = base_scale

        if trade_cnt < args.min_trades:
            # No parameter change on a tiny sample: this is not evidence of
            # strategy quality and otherwise creates feedback-loop overfitting.
            pass
        elif pnl <= -abs(args.pnl_threshold):
            premium *= args.premium_loss_mult
            scale *= args.scale_loss_mult
        elif pnl >= abs(args.pnl_threshold):
            premium *= args.premium_profit_mult
            scale *= args.scale_profit_mult

        premium = clamp(premium, args.premium_floor, args.premium_ceil)
        scale = clamp(scale, args.scale_min, args.scale_max)

        prev = prev_values.get(symbol, {})
        premium_smooth = ema(prev.get("premium"), premium, args.alpha)
        discount_smooth = decimal_ema(prev.get("discount"), discount, args.alpha)
        scale_smooth = ema(prev.get("scale"), scale, args.alpha)

        premium_map[symbol] = premium_smooth
        discount_map[symbol] = discount_smooth
        scale_map[symbol] = scale_smooth

        prev_values[symbol] = {
            "premium": premium_smooth,
            "discount": str(discount_smooth),
            "scale": scale_smooth,
            "pnl": pnl,
            "trades": trade_cnt,
        }

    if premium_map:
        print(f"BUY_VWAP_PREMIUM_MAP={fmt_map(premium_map, args.precision)}")
    if discount_map:
        print(f"BUY_VWAP_DISCOUNT_MAP={fmt_map(discount_map, args.precision)}")
    if scale_map:
        print(f"BUY_VWAP_DISCOUNT_SCALE_MAP={fmt_map(scale_map, args.precision)}")

    save_values(args.state_file, prev_values)
