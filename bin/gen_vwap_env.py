#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: render the VWAP environment configuration.
"""
Динамический расчёт VWAP-параметров для Ladder Dragon.

Использование: python gen_vwap_env.py --symbols SOLUSDT,ETHUSDT ...
Скрипт печатает строки формата KEY=VALUE, которые можно добавлять в dynamic.env.
"""
from __future__ import annotations

import argparse
import math
import sys
from typing import Dict, Iterable, List, Optional, Tuple

from ladder_dragon.execution import tools_market as TM


def ema(series: Iterable[float], period: int) -> float:
    series = list(series)
    if not series:
        return 0.0
    period = max(1, int(period))
    k = 2.0 / (period + 1.0)
    value = series[0]
    for point in series[1:]:
        value = point * k + value * (1.0 - k)
    return value


def compute_atr(klines: List[List[float]], period: int = 14) -> float:
    if len(klines) < period + 1:
        return 0.0
    highs = [float(x[2]) for x in klines]
    lows = [float(x[3]) for x in klines]
    closes = [float(x[4]) for x in klines]
    trs: List[float] = []
    prev_close = closes[0]
    for idx in range(1, len(closes)):
        high = highs[idx]
        low = lows[idx]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = closes[idx]
    if not trs:
        return 0.0
    tail = trs[-max(period * 3, period):]
    return ema(tail, period)


def infer_mode(closes: List[float], ema_fast_len: int = 20, ema_slow_len: int = 50, eps: float = 0.0005) -> str:
    if len(closes) < ema_slow_len:
        return "FLAT"
    ema_fast = ema(closes[-ema_fast_len:], ema_fast_len)
    ema_slow = ema(closes[-ema_slow_len:], ema_slow_len)
    slope = 0.0
    if len(closes) >= ema_fast_len + 1:
        last_fast = ema(closes[-ema_fast_len - 1:-1], ema_fast_len)
        last_price = closes[-1]
        slope = ((ema_fast - last_fast) / max(1.0, abs(last_price)))
    if ema_fast > ema_slow * (1.0 + eps) and slope >= eps:
        return "UP"
    if ema_fast < ema_slow * (1.0 - eps) and slope <= -eps:
        return "DOWN"
    return "FLAT"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def fmt_pairs(pairs: Dict[str, float], precision: int = 6) -> str:
    return ",".join(f"{sym}:{val:.{precision}f}" for sym, val in pairs.items())


def emit_lines(lines: Iterable[str]) -> bool:
    """Напечатать результат и спокойно завершиться при закрытом stdout.

    При остановке systemd родительский supervisor закрывает pipe раньше
    генератора VWAP. Это штатная часть graceful shutdown, а не ошибка расчёта.
    Поэтому BrokenPipeError не должен превращаться в traceback в журнале.
    """
    try:
        for line in lines:
            print(line, flush=True)
    except BrokenPipeError:
        return False
    return True


def build_maps(symbols: List[str], args: argparse.Namespace) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    premium_map: Dict[str, float] = {}
    discount_map: Dict[str, float] = {}
    scale_map: Dict[str, float] = {}

    for symbol in symbols:
        kl = TM.get_klines(symbol, args.interval, limit=max(args.window + 10, 120))
        if not isinstance(kl, list) or len(kl) < 10:
            continue

        closes = [float(x[4]) for x in kl]
        close = closes[-2] if len(closes) >= 2 else closes[-1]
        atr_abs = compute_atr(kl, period=args.atr_period)
        atr_pct = (atr_abs / close) if close > 0 else 0.0
        mode = infer_mode(closes, ema_fast_len=args.ema_fast, ema_slow_len=args.ema_slow, eps=args.dir_eps)

        premium = args.base_premium
        if mode == "UP":
            premium *= args.premium_up_mult
        elif mode == "DOWN":
            premium *= args.premium_down_mult
        premium *= max(0.1, 1.0 - atr_pct * args.premium_atr_coef)
        premium = clamp(premium, args.premium_floor, args.premium_ceil)

        discount = args.base_discount
        scale = args.base_scale
        scale *= 1.0 + atr_pct * args.scale_atr_coef
        scale = clamp(scale, args.scale_min, args.scale_max)

        premium_map[symbol] = premium
        if discount > 0:
            discount_map[symbol] = discount
        if abs(scale - 1.0) > 1e-4:
            scale_map[symbol] = scale

    return premium_map, discount_map, scale_map


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--window", type=int, default=240)
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--dir-eps", type=float, default=0.0005)

    parser.add_argument("--base-premium", type=float, default=0.0030)
    parser.add_argument("--base-discount", type=float, default=0.0060)
    parser.add_argument("--base-scale", type=float, default=1.30)

    parser.add_argument("--premium-up-mult", type=float, default=0.75)
    parser.add_argument("--premium-down-mult", type=float, default=1.20)
    parser.add_argument("--premium-atr-coef", type=float, default=0.0)
    parser.add_argument("--premium-floor", type=float, default=0.0008)
    parser.add_argument("--premium-ceil", type=float, default=0.0060)

    parser.add_argument("--scale-atr-coef", type=float, default=2.0)
    parser.add_argument("--scale-min", type=float, default=1.0)
    parser.add_argument("--scale-max", type=float, default=2.5)

    parser.add_argument("--precision", type=int, default=6)

    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("# VWAP generator: no symbols provided", file=sys.stderr)
        sys.exit(1)

    premium_map, discount_map, scale_map = build_maps(symbols, args)

    lines = []
    if premium_map:
        lines.append(f"BUY_VWAP_PREMIUM_MAP={fmt_pairs(premium_map, args.precision)}")
    if discount_map:
        lines.append(f"BUY_VWAP_DISCOUNT_MAP={fmt_pairs(discount_map, args.precision)}")
    if scale_map:
        lines.append(f"BUY_VWAP_DISCOUNT_SCALE_MAP={fmt_pairs(scale_map, args.precision)}")
    emit_lines(lines)


if __name__ == "__main__":
    main()
