# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: orchestrate the unchanged percentage-ladder command.

from decimal import Decimal, getcontext
getcontext().prec = 28

from dotenv import load_dotenv
load_dotenv()

from ladder_dragon.strategy.ladder_pct_market import die, calc_atr, _filters_decimal, _now_price_decimal
from ladder_dragon.strategy.ladder_pct_parser import parse_args, parse_percentages
from ladder_dragon.strategy.ladder_pct_math import round_down_to_step, round_up_to_step, fmt_decimal, uniq_keep, thin_ticks, thin_abs_pct, raw_levels
from ladder_dragon.strategy.ladder_pct_dispatch import check_min_notional, launch_executor


def main():
    try:
        import numpy as np
    except ImportError as e:
        die(f"NumPy is required: pip install numpy ({e})", code=5)
    args = parse_args()
    symbol = args.symbol.upper()

    # ladder-pct
    min_pct_in, max_pct_in, density = parse_percentages(args)

    now  = _now_price_decimal(symbol)
    flt  = _filters_decimal(symbol)
    tick = flt["tickSize"]

    # Soft ATR scaling.
    atr_abs = calc_atr(symbol)
    min_pct, max_pct, atr_pct, buy_q, sell_q = raw_levels(now, tick, min_pct_in, max_pct_in, density, np, atr_abs)

    # Deduplicate by the string representation after rounding.

    buy_q  = uniq_keep(buy_q)
    sell_q = uniq_keep(sell_q)

    # Price offsets.
    mb = Decimal(str(max(0.0, args.min_buy_offset_pct)))
    ms = Decimal(str(max(0.0, args.min_sell_offset_pct)))
    if mb > 0:
        buy_threshold = now * (Decimal(1) - mb/Decimal(100))
        buy_q = [lv for lv in buy_q if lv <= buy_threshold]
    if ms > 0:
        sell_threshold = now * (Decimal(1) + ms/Decimal(100))
        sell_q = [lv for lv in sell_q if lv >= sell_threshold]

    # Worker order.
    buy_q_sorted  = sorted(buy_q,  reverse=True)
    sell_q_sorted = sorted(sell_q, reverse=False)

    # Minimum distance in ticks.

    buy_q_sorted  = thin_ticks(buy_q_sorted,  tick, int(args.min_ticks_gap))
    sell_q_sorted = thin_ticks(sell_q_sorted, tick, int(args.min_ticks_gap))

    # Minimum absolute relative distance in percent.

    gap_pct = Decimal(str(max(0.0, args.min_abs_gap_pct)))
    buy_q_sorted  = thin_abs_pct(buy_q_sorted,  gap_pct)
    sell_q_sorted = thin_abs_pct(sell_q_sorted, gap_pct)

    # Validate against minNotional.
    check_min_notional(args, flt)

    # --- Nudge the nearest level(s) when enabled ---
    def reflow_side(seq, ascending: bool) -> list[Decimal]:
        """Handle reflow side."""
        seq_sorted = sorted(seq, reverse=not ascending)
        seq_sorted = thin_ticks(seq_sorted, tick, int(args.min_ticks_gap))
        seq_sorted = thin_abs_pct(seq_sorted, gap_pct)
        return seq_sorted

    # SELL nudge: honor the minimum offset after nudging.
    if args.nudge_first_sell and sell_q_sorted:
        if tick > 0 and sell_q_sorted[0] <= now:
            nudged = round_up_to_step(now + tick, tick)
            # Honor min-sell-offset-pct when configured.
            if ms > 0:
                sell_threshold = now * (Decimal(1) + ms/Decimal(100))
                if nudged < sell_threshold:
                    nudged = round_up_to_step(sell_threshold, tick)
            if nudged > sell_q_sorted[0]:
                sell_q_sorted[0] = nudged
                sell_q_sorted = reflow_side(sell_q_sorted, ascending=True)

    # BUY nudge: honor the minimum offset after nudging.
    if args.nudge_first_buy and buy_q_sorted:
        if tick > 0 and buy_q_sorted[0] >= now:
            nudged = round_down_to_step(now - tick, tick)
            if mb > 0:
                buy_threshold = now * (Decimal(1) - mb/Decimal(100))
                if nudged > buy_threshold:
                    nudged = round_down_to_step(buy_threshold, tick)
            if nudged < buy_q_sorted[0]:
                buy_q_sorted[0] = nudged
                buy_q_sorted = reflow_side(buy_q_sorted, ascending=False)

    # Apply --one-side.
    if args.one_side == "buys":
        levels_all = buy_q_sorted
    elif args.one_side == "sells":
        levels_all = sell_q_sorted
    else:
        levels_all = buy_q_sorted + sell_q_sorted

    # If filtering removes every level, follow the configured flag.
    if not levels_all:
        msg = f"[EMPTY] {symbol}: no levels remain after filtering."
        if args.kill_if_empty:
            die(msg + " Exiting because --kill-if-empty is enabled.", code=4)
        else:
            print("[WARN]", msg, "Skipping the executor for this symbol.")
            return 0

    levels_str = ",".join(fmt_decimal(lv) for lv in levels_all)

    print(f"[LADDER] {symbol} now≈{fmt_decimal(now)}  "
          f"pct_in={min_pct_in},{max_pct_in}  scaled={fmt_decimal(min_pct)},{fmt_decimal(max_pct)}  "
          f"ATR%={atr_pct:.4f}  counts(buy/sell)={len(buy_q_sorted)}/{len(sell_q_sorted)} total={len(levels_all)}  "
          f"one_side={args.one_side} gap={args.min_ticks_gap}t/{float(gap_pct):.3f}% "
          f"offsets(buy/sell)={float(mb):.3f}%/{float(ms):.3f}% "
          f"nudge(buy/sell)={'Y' if args.nudge_first_buy else 'N'}/{'Y' if args.nudge_first_sell else 'N'}")

    print(f"[FILTERS] tickSize={fmt_decimal(tick)} minNotional={fmt_decimal(flt['minNotional'])}"
          + (f" stepSize={fmt_decimal(flt['stepSize'])}" if flt['stepSize'] else ""))

    # Executor command.
    return launch_executor(args, symbol, levels_str)
