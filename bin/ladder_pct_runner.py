#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run the percentage ladder strategy.
"""Ladder Dragon ladder pct runner support."""

import os, sys, argparse, subprocess
from decimal import Decimal, getcontext
getcontext().prec = 28

from dotenv import load_dotenv
load_dotenv()

# Shared Binance integration module.
from ladder_dragon.execution import tools_market as TM
from product_version import product_label


def die(msg, code=2):
    print("[ERR]", msg, file=sys.stderr); sys.exit(code)


def round_down_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step is None or step <= 0: return value
    return (value // step) * step


def round_up_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step is None or step <= 0: return value
    if (value % step) == 0: return value
    return ((value // step) + 1) * step


def fmt_decimal(d: Decimal) -> str:
    s = f"{d.normalize():f}"
    return s.rstrip('0').rstrip('.') if '.' in s else s


def calc_atr(symbol: str, interval: str = "1h", window: int = 14) -> float:
    """Calculate atr."""
    k = TM.get_klines(symbol, interval, limit=max(window + 2, 16))
    if not k or len(k) < 2:
        return 0.0
    highs = [float(x[2]) for x in k]
    lows  = [float(x[3]) for x in k]
    closes= [float(x[4]) for x in k]
    trs = []
    for i in range(1, len(k)):
        h,l,c_prev = highs[i], lows[i], closes[i-1]
        trs.append(max(h-l, abs(h-c_prev), abs(l-c_prev)))
    return sum(trs)/len(trs) if trs else 0.0


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


def _filters_decimal(symbol: str) -> dict:
    """Handle filters decimal."""
    f = TM.get_symbol_filters(symbol)
    D = Decimal
    try:
        tick = D(str(f.get("tickSize") or "0.01"))
        if tick <= 0:
            die(f"Invalid tickSize for {symbol}: {tick}", code=6)
    except Exception as e:
        die(f"Bad filters for {symbol}: {e}", code=6)
    out = {
        "tickSize": D(str(f.get("tickSize", "0.01") or "0.01")),
        "stepSize": D(str(f.get("stepSize", "0") or "0")) if f.get("stepSize") else None,
        "minQty":   D(str(f.get("minQty", "0") or "0"))   if f.get("minQty")   else None,
        "minNotional": D(str(f.get("minNotional", "5") or "5")),
    }
    return out


def _now_price_decimal(symbol: str) -> Decimal:
    try:
        px = TM.get_ticker_price(symbol)
        return Decimal(str(px))
    except TM.BinanceHttpError as e:
        die(f"Failed to fetch ticker price: {e}")


def main():
    try:
        import numpy as np
    except Exception as e:
        die(f"NumPy is required: pip install numpy ({e})", code=5)
    args = parse_args()
    symbol = args.symbol.upper()

    # ladder-pct
    try:
        D_ = Decimal
        raw = [x.strip() for x in args.ladder_pct.split(",") if x.strip() != ""]
        if len(raw) not in (2,3): die("ladder-pct must be '-min%,-max%,[density]'. Example: -0.5,-20,20")
        min_pct_in, max_pct_in = D_(raw[0]), D_(raw[1])
        density = int(raw[2]) if len(raw) == 3 else int(args.grid_density)
        density = max(2, min(density, 256))
        if not (min_pct_in < 0 and max_pct_in < 0 and abs(max_pct_in) >= abs(min_pct_in)):
            die("Both percentages must be negative and |max|>=|min| (for example -0.5,-20)")
    except Exception:
        die("bad --ladder-pct format")

    now  = _now_price_decimal(symbol)
    flt  = _filters_decimal(symbol)
    tick = flt["tickSize"]

    # Soft ATR scaling.
    atr_abs = calc_atr(symbol)
    atr_pct = (atr_abs / float(now)) if now > 0 else 0.0
    scale_factor = Decimal(str(1 + atr_pct * 0.5))

    min_pct = (min_pct_in * scale_factor)
    max_pct = (max_pct_in * scale_factor)

    # Geometric spacing by magnitude.
    start_mag = float(abs(min_pct))
    stop_mag  = float(abs(max_pct))
    if abs(start_mag - stop_mag) < 1e-12:
        mags = [start_mag] * density
    else:
        mags = np.geomspace(start_mag, stop_mag, num=density).tolist()

    buy_pcts  = [-Decimal(str(m)) for m in mags]
    sell_pcts = [ Decimal(str(m)) for m in mags]

    # Levels.
    buy_levels  = [now * (Decimal(1) + p/Decimal(100)) for p in buy_pcts]
    sell_levels = [now * (Decimal(1) + p/Decimal(100)) for p in sell_pcts]

    # Rounding.
    buy_q  = [round_down_to_step(lv, tick) for lv in buy_levels]
    sell_q = [round_up_to_step(lv,   tick) for lv in sell_levels]

    # Deduplicate by the string representation after rounding.
    def uniq_keep(seq):
        seen, out = set(), []
        for x in seq:
            k = fmt_decimal(x)
            if k not in seen:
                seen.add(k); out.append(x)
        return out

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
    def thin_ticks(seq, tick, min_ticks: int) -> list[Decimal]:
        if min_ticks <= 0 or tick <= 0 or len(seq) <= 1:
            return seq
        out, last = [], None
        gap = tick * Decimal(min_ticks)
        for x in seq:
            if last is None or abs(x - last) >= gap:
                out.append(x); last = x
        return out

    buy_q_sorted  = thin_ticks(buy_q_sorted,  tick, int(args.min_ticks_gap))
    sell_q_sorted = thin_ticks(sell_q_sorted, tick, int(args.min_ticks_gap))

    # Minimum absolute relative distance in percent.
    def thin_abs_pct(seq, min_pct_gap: Decimal) -> list[Decimal]:
        if min_pct_gap <= 0 or len(seq) <= 1:
            return seq
        out, last = [], None
        for x in seq:
            if last is None:
                out.append(x); last = x
            else:
                rel = abs((x - last) / last) * Decimal(100)
                if rel >= min_pct_gap:
                    out.append(x); last = x
        return out

    gap_pct = Decimal(str(max(0.0, args.min_abs_gap_pct)))
    buy_q_sorted  = thin_abs_pct(buy_q_sorted,  gap_pct)
    sell_q_sorted = thin_abs_pct(sell_q_sorted, gap_pct)

    # Validate against minNotional.
    eff_order_usdt = None
    if args.min_order_usdt and args.min_order_usdt > 0:
        eff_order_usdt = Decimal(str(args.min_order_usdt))
    else:
        cap_env = os.getenv("BOT_CAP_PER_ORDER")
        if cap_env:
            try: eff_order_usdt = Decimal(str(cap_env))
            except: eff_order_usdt = None

    if eff_order_usdt is not None and flt["minNotional"] is not None and flt["minNotional"] > 0:
        min_not = flt["minNotional"]
        if eff_order_usdt < min_not:
            msg = (f"effective order USDT ({fmt_decimal(eff_order_usdt)}) is below minNotional "
                   f"({fmt_decimal(min_not)}).")
            if args.strict_minnotional:
                die(msg + " Exiting because --strict-minnotional is enabled.", code=3)
            else:
                print("[WARN]", msg, "Consider increasing CAP.")

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
    cmd = ["python3", "-u", args.base_script, "--symbol", symbol, "--ladder-prices", levels_str]
    if args.live: cmd.append("--live")
    if args.only_new_fills: cmd.append("--only-new-fills")
    cmd += ["--max-oco-per-symbol", str(args.max_oco_per_symbol)]
    cmd += ["--tp1", str(args.tp1), "--tp2", str(args.tp2), "--sl", str(args.sl)]
    cmd += ["--status-interval", str(args.status_interval), "--loop-minutes", str(args.loop_minutes)]

    print("[LAUNCH]", " ".join(cmd))
    try:
        res = subprocess.run(cmd, check=False)
        sys.exit(res.returncode)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Stopped by user."); sys.exit(130)


if __name__ == "__main__":
    main()
