#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: run the AI planning loop under the configured safety policy.
"""English documentation."""

from __future__ import annotations

import os
import sys
import math
import time
import shlex
import argparse
import subprocess
import threading
import contextlib
from typing import List, Tuple, Optional, Dict
from product_version import product_label

try:
    import requests
except Exception:
    print("Please: pip install requests", file=sys.stderr)
    raise

# --- Settings / ENV ---
DEFAULT_BASE = os.getenv("PLAN_RUNNER_BASE", "bin/autosize_universal.py")
BINANCE_API = (os.getenv("BINANCE_BASE_URL") or os.getenv("BINANCE_API_BASE") or "https://api.binance.com").rstrip("/")


# --- Public API helpers (unsigned) ---

def _public_get(path: str, params: Dict | None = None, timeout: int = 12) -> Dict:
    url = BINANCE_API + path
    last_err = None
    for i in range(3):  # English maintenance note.
        try:
            r = requests.get(url, params=params or {}, timeout=timeout)
            if r.status_code in (418, 429) or 500 <= r.status_code < 600:
                # Backoff.
                time.sleep(0.7 * (2 ** i))
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text}")
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (2 ** i))
    raise last_err if last_err else RuntimeError("Public GET failed without explicit error")

def get_now_price(symbol: str) -> float:
    j = _public_get("/api/v3/ticker/price", {"symbol": symbol})
    return float(j["price"])

def get_filters(symbol: str) -> Tuple[float, float, float]:
    """Return (tickSize, stepSize, minNotional); only tickSize is used for prices here."""
    info = _public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    s = info["symbols"][0]
    tick = step = min_notional = 0.0
    for f in s["filters"]:
        t = f.get("filterType")
        if t == "PRICE_FILTER":
            tick = float(f.get("tickSize", 0.0) or 0.0)
        elif t == "LOT_SIZE":
            step = float(f.get("stepSize", 0.0) or 0.0)
        elif t in ("MIN_NOTIONAL", "NOTIONAL"):
            try:
                min_notional = float(f.get("minNotional", 5.0))
            except Exception:
                min_notional = 5.0
    return tick, step, min_notional


# --- Ladder mathematics ---

def _geomspace(a: float, b: float, n: int) -> List[float]:
    """English documentation."""
    if n <= 1:
        return [a]
    sign = -1.0 if a < 0 else 1.0
    A, B = abs(a), abs(b)
    if A <= 0 or B <= 0:
        # Fall back to a linear sequence when inputs are invalid.
        step = (b - a) / (n - 1)
        return [a + i * step for i in range(n)]
    # Build a geometric scale by magnitude, then restore signs for lower percentages.
    out = []
    for i in range(n):
        t = i / (n - 1)
        val = A * (B / A) ** t
        out.append(sign * val)
    return out

def _round_price_down(p: float, tick: float) -> float:
    if tick <= 0:
        return p
    return math.floor(p / tick) * tick

def _round_price_up(p: float, tick: float) -> float:
    if tick <= 0:
        return p
    return math.ceil(p / tick) * tick

def _dedup_preserve(seq: List[float]) -> List[float]:
    out, seen = [], set()
    for x in seq:
        k = f"{x:.12f}"
        if k not in seen:
            out.append(x)
            seen.add(k)
    return out

def _preview_levels(levels: List[float], n: int = 3) -> str:
    """English documentation."""
    if not levels:
        return "[] (n=0)"
    head = ", ".join(f"{x:.8f}" for x in levels[:n])
    if len(levels) > n:
        tail = ", ".join(f"{x:.8f}" for x in levels[-n:])
        return f"[{head} … {tail}] (n={len(levels)})"
    return f"[{head}] (n={len(levels)})"

def build_ladder_pct(now_price: float,
                     pct_low: float, pct_high: float, density: int,
                     tick: float,
                     atr_scale: float | None = None) -> List[float]:
    """English documentation."""
    # Scale percentages when atr_scale is provided.
    if atr_scale and atr_scale > 0:
        pct_low  = pct_low  * atr_scale
        pct_high = pct_high * atr_scale

    lows  = _geomspace(pct_low,  pct_low * 0.1, max(2, density))  # English maintenance note.
    highs = _geomspace(pct_high, pct_high * 0.1, max(2, density)) # English maintenance note.

    # Convert percentages to prices and quantize them.
    buy_levels_raw  = [_round_price_down(now_price * (1.0 + p / 100.0), tick) for p in lows]   # BUY
    sell_levels_raw = [_round_price_up  (now_price * (1.0 + p / 100.0), tick) for p in highs]  # SELL

    # Filter invalid values.
    buy_levels  = [x for x in buy_levels_raw  if x > 0 and x <= now_price]
    sell_levels = [x for x in sell_levels_raw if x > 0 and x >= now_price]

    # Sort BUY descending (nearest to market first), SELL ascending.
    buy_levels_sorted  = sorted(buy_levels, reverse=True)
    sell_levels_sorted = sorted(sell_levels)

    # Merge and deduplicate while preserving order.
    levels = _dedup_preserve(buy_levels_sorted + sell_levels_sorted)
    return levels


def estimate_atr_ratio(symbol: str, interval: str = "1h", window: int = 14) -> float:
    """English documentation."""
    k = _public_get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": window + 2})
    if len(k) < 2:
        return 0.0
    highs = [float(x[2]) for x in k]
    lows  = [float(x[3]) for x in k]
    closes= [float(x[4]) for x in k]
    trs = []
    for i in range(1, len(k)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr = sum(trs)/len(trs) if trs else 0.0
    last = closes[-1]
    return (atr / last) if last > 0 else 0.0


# --- Child construction and startup ---

def _bool_flag(v: bool, name: str) -> List[str]:
    return [f"--{name}"] if v else []

def _append_opt(name: str, val: Optional[str]) -> List[str]:
    if val is None:
        return []
    s = str(val).strip()
    return [f"--{name}", s] if s else []

def _append_float(name: str, val: Optional[float]) -> List[str]:
    if val is None:
        return []
    return [f"--{name}", f"{val}"]

def spawn_child(py: str,
                base_script: str,
                symbol: str,
                ladder_prices_csv: str | None,
                tp1: float, tp2: float, sl: float,
                status_interval: int, loop_minutes: int,
                oco_on_holdings: bool, live: bool,
                oco_fallback: str) -> subprocess.Popen:
    cmd: List[str] = [py, "-u", base_script,
                      "--symbol", symbol,
                      "--status-interval", str(status_interval),
                      "--loop-minutes", str(loop_minutes)]
    cmd += _append_float("tp1", tp1)
    cmd += _append_float("tp2", tp2)
    cmd += _append_float("sl",  sl)
    cmd += _append_opt("ladder-prices", ladder_prices_csv)
    cmd += _bool_flag(oco_on_holdings, "oco-on-holdings")
    cmd += _bool_flag(live, "live")
    if oco_fallback in ("none", "prefer-tp1"):
        cmd += ["--oco-fallback", oco_fallback]

    print(f"[RUN] {symbol} → {shlex.join(cmd)}", flush=True)

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )

def stream_prefixed(sym: str, proc: subprocess.Popen):
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{sym}] {line.rstrip()}", flush=True)


# --- CLI/MAIN ---

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="English/English English Ladder Dragon")
    p.add_argument("--version", action="version", version=product_label("plan runner"))
    p.add_argument("--symbols", type=str, required=True,
                   help="English English, English: SOLUSDT,ETHUSDT,BTCUSDT")
    p.add_argument("--base", type=str, default=DEFAULT_BASE,
                   help=f"English English English English (default: {DEFAULT_BASE})")

    # Ladder mode.
    p.add_argument("--ladder-mode", choices=["pct", "manual"], default="pct",
                    help="pct — English English English English, manual — English --ladder-prices English English")
    p.add_argument("--ladder-pct", type=str, default="-0.5,20,20",
                help="English English pct: '<min%>,<max%>,<density>'. English: -0.5,20,20")
    p.add_argument("--grid-density", type=int, default=20,
                   help="English English English English English English English pct")
    p.add_argument("--atr-interval", type=str, default="1h")
    p.add_argument("--atr-window", type=int, default=14,
                   help="English English ATR")
    p.add_argument("--atr-scale-k", type=float, default=0.5,
                   help="English English pct English ATR: scale = 1 + ATR_ratio * k")

    # Explicit manual ladder.
    p.add_argument("--ladder-prices", type=str, default="",
                   help="English English English English: '165.82,175.94,...' — English English English English manual")

    # Trading parameters passed to children.
    p.add_argument("--tp1", type=float, default=0.02)
    p.add_argument("--tp2", type=float, default=0.02)
    p.add_argument("--sl",  type=float, default=-0.01)
    p.add_argument("--oco-on-holdings", action="store_true")
    p.add_argument("--oco-fallback", choices=["none", "prefer-tp1"], default="none")
    p.add_argument("--live", action="store_true")

    # Timing parameters.
    p.add_argument("--status-interval", type=int, default=2)
    p.add_argument("--loop-minutes", type=int, default=5)

    return p.parse_args()

def main() -> int:
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("[ERR] English English English.", file=sys.stderr)
        return 2

    base_script = args.base.strip() or DEFAULT_BASE
    if not os.path.exists(base_script):
                # Try next to the current file.
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(here, base_script)
        if os.path.exists(cand):
            base_script = cand
        else:
            print(f"[ERR] English English English English: {args.base}", file=sys.stderr)
            return 3

    py = sys.executable or "python3"

    procs: List[subprocess.Popen] = []
    threads: List[threading.Thread] = []
    try:
        for sym in symbols:
            ladder_csv: Optional[str] = None

            if args.ladder_mode == "manual":
                ladder_csv = args.ladder_prices.strip() or ""
            else:
                # Percentage-based generation.
                now = get_now_price(sym)
                tick, step, min_notional = get_filters(sym)

                if tick <= 0:
                    print(f"[WARN] {sym} tickSize=0 — English English English", file=sys.stderr)

                # Exchange-filter log for diagnostics.
                print(f"[PLAN] {sym} filters: tick={tick:.8f} step={step:.8f} minNotional={min_notional:.4f}")

                # Parse "--ladder-pct".
                try:
                    lo_s, hi_s, den_s = [x.strip() for x in args.ladder_pct.split(",")]
                    pct_low  = -abs(float(lo_s))   # English maintenance note.
                    pct_high =  abs(float(hi_s))   # English maintenance note.
                    density  = int(den_s) if den_s else args.grid_density
                except Exception:
                    pct_low, pct_high, density = -0.5, 20.0, args.grid_density

                # ATR scaling.
                atr_ratio = estimate_atr_ratio(sym, args.atr_interval, args.atr_window)
                scale = 1.0 + max(0.0, atr_ratio) * max(0.0, args.atr_scale_k)

                levels = build_ladder_pct(
                    now_price=now,
                    pct_low=pct_low,
                    pct_high=pct_high,
                    density=max(2, density),
                    tick=tick,
                    atr_scale=scale
                )
                ladder_csv = ",".join(f"{lv:.8f}" for lv in levels)

                # One-time plan diagnostics.
                print(f"[PLAN] {sym} now≈{now:.4f} ATR_ratio≈{atr_ratio:.4f} scale={scale:.3f}")
                print(f"[PLAN] {sym} ladder -> {ladder_csv}")

                # Count levels by side from the final flat list.
                buy_cnt  = sum(1 for x in levels if x <= now)
                sell_cnt = sum(1 for x in levels if x >  now)
                print(f"[PLAN] {sym} levels: BUY={buy_cnt} SELL={sell_cnt}")

                # Side arrays for the preview (build_ladder_pct already returns BUY↓, SELL↑).
                buy_side  = [x for x in levels if x <= now]
                sell_side = [x for x in levels if x >  now]

                print(f"[PLAN] {sym} BUY preview:  {_preview_levels(buy_side)}")
                print(f"[PLAN] {sym} SELL preview: {_preview_levels(sell_side)}")

            # Start the base script.
            proc = spawn_child(
                py=py,
                base_script=base_script,
                symbol=sym,
                ladder_prices_csv=ladder_csv if ladder_csv else None,
                tp1=args.tp1, tp2=args.tp2, sl=args.sl,
                status_interval=args.status_interval, loop_minutes=args.loop_minutes,
                oco_on_holdings=args.oco_on_holdings, live=args.live,
                oco_fallback=args.oco_fallback
            )
            procs.append(proc)

            # Dedicated thread for streaming this subprocess's logs.
            t = threading.Thread(target=stream_prefixed, args=(sym, proc), daemon=True)
            t.start()
            threads.append(t)

        # Wait for all subprocesses to finish.
        for proc in procs:
            proc.wait()
        # Let log threads drain their buffers.
        for t in threads:
            t.join(timeout=1.0)

        # Return codes.
        rc = 0
        for sym, proc in zip(symbols, procs):
            code = proc.poll()
            if code is None:
                code = proc.wait()
            print(f"[DONE] {sym} → exit={code}")
            rc |= 0 if code == 0 else 1
        return rc

    except KeyboardInterrupt:
        print("\n[INTERRUPT] English English Ctrl+C — English English…", file=sys.stderr)
        for proc in procs:
            with contextlib.suppress(Exception):
                proc.terminate()
        for proc in procs:
            with contextlib.suppress(Exception):
                proc.wait(timeout=3.0)
        return 130

    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        for proc in procs:
            with contextlib.suppress(Exception):
                proc.terminate()
        return 1

if __name__ == "__main__":
    sys.exit(main())
