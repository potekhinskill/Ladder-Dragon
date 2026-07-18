#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""
auto_ladder_map.py
Генерит строку для --ladder-pct-map на основе «режима рынка» по каждому символу.

Режимы:
- UP:    ema20>ema50 и положительный наклон ema20, atr_pct >= lowvol_floor
- DOWN:  ema20<ema50 и отрицательный наклон ema20, atr_pct >= lowvol_floor
- FLAT:  иначе (или низковолатильный рынок)

Для каждого символа возвращает триплет: near(%), far(%), tp(%)
(относительно текущей цены; near/far — минусовые, tp — плюсовой)

По умолчанию:
  SOLUSDT: UP    -> -0.6, -3.5, +2.8
           FLAT  -> -0.6, -3.5, +2.8
           DOWN  -> -0.7, -4.0, +3.0
  ETHUSDT: UP    -> -0.5, -3.0, +2.4
           FLAT  -> -0.6, -3.5, +2.8
           DOWN  -> -0.7, -4.0, +3.0
  TONUSDT: UP    -> -0.6, -3.2, +2.6
           FLAT  -> -0.6, -3.5, +2.8
           DOWN  -> -0.7, -4.0, +3.0

Порог «низкой волатильности» (lowvol_floor) = 0.0035 (0.35%)
dir_eps (наклон) = 0.0006 по-умолчанию, как в твоём сервисе.
"""

import os, sys, time, math, json
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BINANCE_API_BASE = (os.getenv("BINANCE_API_BASE") or os.getenv("BINANCE_BASE_URL") or "https://api.binance.com").rstrip("/")
UA = os.getenv("USER_AGENT", "Ladder-Dragon/auto-ladder/1.0")

def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    try:
        retries = Retry(
            total=5, connect=5, read=5, backoff_factor=0.6,
            status_forcelist=(418, 429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),  # v1.26+/v2
            raise_on_status=False,
        )
    except TypeError:
        retries = Retry(
            total=5, connect=5, read=5, backoff_factor=0.6,
            status_forcelist=(418, 429, 500, 502, 503, 504),
            method_whitelist=frozenset(["GET"]),  # старые версии
            raise_on_status=False,
        )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s

def fetch_klines(session, base_url, symbol: str, interval="1m", limit=240, futures=False):
    if futures:
        url = f"https://fapi.binance.com/fapi/v1/klines"
    else:
        url = f"{base_url}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = session.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def ema(series, period):
    k = 2.0 / (period + 1.0)
    ema_val = None
    out = []
    for v in series:
        v = float(v)
        ema_val = v if ema_val is None else (v - ema_val) * k + ema_val
        out.append(ema_val)
    return out

def atr_pct_from_klines(kl):
    highs = [float(x[2]) for x in kl]
    lows  = [float(x[3]) for x in kl]
    closes= [float(x[4]) for x in kl]
    if len(closes) < 16:
        return 0.0
    trs = []
    prev_close = closes[0]
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-prev_close), abs(lows[i]-prev_close))
        trs.append(tr)
        prev_close = closes[i]
    n=14
    if len(trs) < n:
        return 0.0
    atr = sum(trs[:n]) / n
    for v in trs[n:]:
        atr = (atr*(n-1) + v) / n  # RMA
    last_close = closes[-1]
    return (atr / last_close) if last_close > 0 else 0.0

def interval_minutes(interval: str) -> float:
    try:
        unit = interval[-1].lower()
        val = float(interval[:-1])
    except Exception:
        return 1.0
    return val if unit=='m' else val*60.0 if unit=='h' else val*1440.0 if unit=='d' else 1.0

def regime_from(klines, dir_eps=0.0006, lowvol_floor=0.0035, interval="1m", ignore_last=False):
    # опция ignore_last=True — можно исключить последний незакрытый бар
    if ignore_last and len(klines) > 1:
        klines = klines[:-1]
    closes = [float(x[4]) for x in klines]
    if len(closes) < 60:
        print(f"[INFO] len(closes)={len(closes)} < 60 → FLAT", file=sys.stderr)
        return "FLAT"
    # масштабируем порог наклона под интервал (эталон — 1m)
    scale = max(1.0, interval_minutes(interval) / 1.0)
    adj_dir_eps = dir_eps * scale

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    e20, e20_prev = ema20[-1], ema20[-2]
    e50 = ema50[-1]
    last = closes[-1]
    slope = (e20 - e20_prev) / last if last > 0 else 0.0
    atrp = atr_pct_from_klines(klines)

    if atrp < lowvol_floor:
        return "FLAT"
    if e20 > e50 and slope >  adj_dir_eps: return "UP"
    if e20 < e50 and slope < -adj_dir_eps: return "DOWN"
    return "FLAT"

DEFAULT_PRESETS = {
    "SOLUSDT": {
        "UP":   (-0.6, -3.5, +2.8),
        "FLAT": (-0.6, -3.5, +2.8),
        "DOWN": (-0.7, -4.0, +3.0),
    },
    "ETHUSDT": {
        "UP":   (-0.5, -3.0, +2.4),
        "FLAT": (-0.6, -3.5, +2.8),
        "DOWN": (-0.7, -4.0, +3.0),
    },
    "TONUSDT": {
        "UP":   (-0.6, -3.2, +2.6),
        "FLAT": (-0.6, -3.5, +2.8),
        "DOWN": (-0.7, -4.0, +3.0),
    },
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SOLUSDT,ETHUSDT,TONUSDT")
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--limit", type=int, default=240)
    ap.add_argument("--dir-eps", type=float, default=float(os.getenv("DIR_EPS", "0.0006")), help="базовый порог для 1m; масштабируется по интервалу внутри")
    ap.add_argument("--lowvol-floor", type=float, default=0.0035)
    ap.add_argument("--preset-json", default=os.getenv("LADDER_PRESET_JSON",""))
    ap.add_argument("--format", choices=["raw","supervisor"], default="supervisor")
    ap.add_argument("--futures", action="store_true", help="брать свечи с /fapi/v1/klines")
    ap.add_argument("--ignore-last", action="store_true", help="не учитывать последний незакрытый бар")
    args = ap.parse_args()

    presets = dict(DEFAULT_PRESETS)
    if args.preset_json:
        try:
            custom = json.loads(args.preset_json)
            for sym, mp in custom.items():
                presets.setdefault(sym, {})
                for k, v in mp.items():
                    if not (isinstance(v, (list, tuple)) and len(v) == 3):
                        raise ValueError(f"bad preset for {sym}/{k}: {v}")
                    presets[sym][k.upper()] = (float(v[0]), float(v[1]), float(v[2]))
        except Exception as e:
            print(f"[WARN] bad LADDER_PRESET_JSON: {e}", file=sys.stderr)

    session = make_session()
    out_parts = []
    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        try:
            kl = fetch_klines(session, BINANCE_API_BASE, sym, args.interval, args.limit, futures=args.futures)
            reg = regime_from(kl, dir_eps=args.dir_eps, lowvol_floor=args.lowvol_floor,
                              interval=args.interval, ignore_last=args.ignore_last)
            trip = presets.get(sym, presets["SOLUSDT"]).get(reg, presets.get(sym, presets["SOLUSDT"])["FLAT"])
            near, far, tp = trip
            seg = f"{sym}={near:.3f},{far:.3f},{tp:.3f}"
            out_parts.append(seg)
            print(f"[{sym}] regime={reg} → {seg}", file=sys.stderr)
        except Exception as e:
            trip = presets.get(sym, presets["SOLUSDT"])["FLAT"]
            near, far, tp = trip
            seg = f"{sym}={near:.3f},{far:.3f},{tp:.3f}"
            out_parts.append(seg)
            print(f"[{sym}] ERROR {e} → fallback FLAT: {seg}", file=sys.stderr)

    s = ";".join(out_parts)
    print(s if args.format == "supervisor" else json.dumps({"ladder_pct_map": s}))

if __name__ == "__main__":
    main()
