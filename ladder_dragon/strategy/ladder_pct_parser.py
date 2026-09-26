# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own percentage-ladder arguments and percentage parsing.

import argparse
from decimal import Decimal
from product_version import product_label
from ladder_dragon.strategy.ladder_pct_market import die


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--version", action="version", version=product_label("ladder runner"))
    p.add_argument("--symbol", required=True)
    # Format: -min%,-max%,[density] (example: -0.5,-20,20).
    p.add_argument("--ladder-pct", type=str, default="-0.5,-20,20")
    p.add_argument("--grid-density", type=int, default=20)
    p.add_argument("--base-script", type=str, default="bin/autosize_universal.py")
    p.add_argument("--kill-if-empty", action="store_true",
                   help="Exit with an error if filtering removes every level.")

    # Configure side and distances.
    p.add_argument("--one-side", choices=("buys","sells","both"), default="both",
                   help="Keep buy levels, sell levels, or both sides.")
    p.add_argument("--min-ticks-gap", type=int, default=0,
                   help="Minimum spacing between adjacent levels in ticks (0 disables the limit).")
    p.add_argument("--min-abs-gap-pct", type=float, default=0.0,
                   help="Minimum relative spacing between adjacent levels in percent (0 disables the limit).")
    p.add_argument("--min-buy-offset-pct", type=float, default=0.0,
                   help="Do not place BUY levels closer than X%% below the current price.")
    p.add_argument("--min-sell-offset-pct", type=float, default=0.0,
                   help="Do not place SELL levels closer than Y%% above the current price.")
    p.add_argument("--nudge-first-sell", action="store_true",
                    help="Move the first SELL up by one tick when it is at or below market.")
    p.add_argument("--nudge-first-buy", action="store_true",
                    help="Move the first BUY down by one tick when it is at or above market.")

    # Validate against minNotional.
    p.add_argument("--min-order-usdt", type=float, default=None,
                   help="Estimated per-order USDT cap used for the minNotional check.")
    p.add_argument("--strict-minnotional", action="store_true",
                   help="Exit without emitting levels when CAP is below minNotional.")

    # Passthrough to the executor.
    p.add_argument("--live", action="store_true")
    p.add_argument("--only-new-fills", action="store_true")
    p.add_argument("--max-oco-per-symbol", type=int, default=4)
    p.add_argument("--tp1", type=float, default=0.08)
    p.add_argument("--tp2", type=float, default=0.08)
    p.add_argument("--sl",  type=float, default=-0.015)
    p.add_argument("--status-interval", type=int, default=1)
    p.add_argument("--loop-minutes", type=int, default=5)
    return p.parse_args()


def parse_percentages(args):
    try:
        D_ = Decimal
        raw = [x.strip() for x in args.ladder_pct.split(",") if x.strip() != ""]
        if len(raw) not in (2,3): die("ladder-pct must be '-min%,-max%,[density]'. Example: -0.5,-20,20")
        min_pct_in, max_pct_in = D_(raw[0]), D_(raw[1])
        density = int(raw[2]) if len(raw) == 3 else int(args.grid_density)
        density = max(2, min(density, 256))
        if not (min_pct_in < 0 and max_pct_in < 0 and abs(max_pct_in) >= abs(min_pct_in)):
            die("Both percentages must be negative and |max|>=|min| (for example -0.5,-20)")
    except (TypeError, ValueError, ArithmeticError):
        die("bad --ladder-pct format")
    return min_pct_in, max_pct_in, density
