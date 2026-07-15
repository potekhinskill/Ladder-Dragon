#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_plan_runner.py — оркестратор + генератор лесенки (pct/ATR) для 1.8_autosize_universal.py

Задача:
- Не создавать ордера напрямую.
- При необходимости сгенерировать лесенку цен (вниз/вверх) из процентов (включая ATR-масштаб),
  округлить уровни по tickSize и передать их в 1.8_autосize_universal.py.
- Запустить по нескольким символам и аккуратно ретранслировать логи.

Примеры:
  python3 ai_plan_runner.py \
    --symbols SOLUSDT,ETHUSDT \
    --ladder-mode pct --ladder-pct "-0.5,20,20" --grid-density 20 \
    --tp1 0.06 --tp2 0.08 --sl -0.015 \
    --oco-on-holdings --oco-fallback prefer-tp1 \
    --status-interval 2 --loop-minutes 5 \
    --live
"""

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

try:
    import requests
except Exception:
    print("Please: pip install requests", file=sys.stderr)
    raise

# --- Настройки/ENV ---
DEFAULT_BASE = os.getenv("PLAN_RUNNER_BASE", "1.8_autosize_universal.py")
BINANCE_API = (os.getenv("BINANCE_BASE_URL") or os.getenv("BINANCE_API_BASE") or "https://api.binance.com").rstrip("/")


# --- Утилиты публичного API (без подписи) ---

def _public_get(path: str, params: Dict | None = None, timeout: int = 12) -> Dict:
    url = BINANCE_API + path
    last_err = None
    for i in range(3):  # до 3 попыток
        try:
            r = requests.get(url, params=params or {}, timeout=timeout)
            if r.status_code in (418, 429) or 500 <= r.status_code < 600:
                # бэкофф
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
    """Возвращает (tickSize, stepSize, minNotional). stepSize тут не используем — только tickSize для цен."""
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


# --- Математика для лесенки ---

def _geomspace(a: float, b: float, n: int) -> List[float]:
    """Геометрическая прогрессия между |a| и |b|, со знаком a; n>=2."""
    if n <= 1:
        return [a]
    sign = -1.0 if a < 0 else 1.0
    A, B = abs(a), abs(b)
    if A <= 0 or B <= 0:
        # fallback на линейную, если что-то не так
        step = (b - a) / (n - 1)
        return [a + i * step for i in range(n)]
    # геометрическая шкала по модулю, затем восстанавливаем знак для нижних процентов
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
    """Короткий превью-лог: первые и последние n уровней, с размером массива."""
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
    """
    Генерирует уровни вниз (buy) и вверх (sell) от текущей цены согласно процентам.
    pct_low < 0, pct_high > 0, density — количество уровней в каждую сторону.
    atr_scale — множитель для адаптации к волатильности (например 1 + ATR_ratio*0.5).

    Порядок в результате:
      - Сначала BUY-уровни, отсортированные по убыванию (от ближних к дальним),
      - затем SELL-уровни, отсортированные по возрастанию (от ближних к дальним).
    """
    # масштабируем проценты, если задан atr_scale
    if atr_scale and atr_scale > 0:
        pct_low  = pct_low  * atr_scale
        pct_high = pct_high * atr_scale

    lows  = _geomspace(pct_low,  pct_low * 0.1, max(2, density))  # снизу
    highs = _geomspace(pct_high, pct_high * 0.1, max(2, density)) # сверху

    # проценты -> цены + квантование
    buy_levels_raw  = [_round_price_down(now_price * (1.0 + p / 100.0), tick) for p in lows]   # BUY
    sell_levels_raw = [_round_price_up  (now_price * (1.0 + p / 100.0), tick) for p in highs]  # SELL

    # фильтруем мусор
    buy_levels  = [x for x in buy_levels_raw  if x > 0 and x <= now_price]
    sell_levels = [x for x in sell_levels_raw if x > 0 and x >= now_price]

    # сортировка: BUY — по убыванию (ближе к рынку сначала), SELL — по возрастанию
    buy_levels_sorted  = sorted(buy_levels, reverse=True)
    sell_levels_sorted = sorted(sell_levels)

    # объединяем и дедупим, сохраняя порядок
    levels = _dedup_preserve(buy_levels_sorted + sell_levels_sorted)
    return levels


def estimate_atr_ratio(symbol: str, interval: str = "1h", window: int = 14) -> float:
    """
    Возвращает ATR/price (долю от цены). Упрощённая реализация по kline.
    """
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


# --- Сборка и запуск детей ---

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
    p = argparse.ArgumentParser(description="Оркестратор/генератор лесенки для 1.8_autosize_universal.py")
    p.add_argument("--symbols", type=str, required=True,
                   help="Список символов, например: SOLUSDT,ETHUSDT,BTCUSDT")
    p.add_argument("--base", type=str, default=DEFAULT_BASE,
                   help=f"Путь к базовому скрипту (default: {DEFAULT_BASE})")

    # Режим лесенки
    p.add_argument("--ladder-mode", choices=["pct", "manual"], default="pct",
                    help="pct — генерить лесенку из процентов, manual — принять --ladder-prices как есть")
    p.add_argument("--ladder-pct", type=str, default="-0.5,20,20",
                help="Параметры для pct: '<min%>,<max%>,<density>'. Пример: -0.5,20,20")
    p.add_argument("--grid-density", type=int, default=20,
                   help="Сколько уровней в каждую сторону в режиме pct")
    p.add_argument("--atr-interval", type=str, default="1h")
    p.add_argument("--atr-window", type=int, default=14,
                   help="Длина окна ATR")
    p.add_argument("--atr-scale-k", type=float, default=0.5,
                   help="Коэффициент масштабирования pct по ATR: scale = 1 + ATR_ratio * k")

    # Явная лесенка (manual)
    p.add_argument("--ladder-prices", type=str, default="",
                   help="Список цен через запятую: '165.82,175.94,...' — используется только в режиме manual")

    # Торговые параметры (пробрасываются вниз)
    p.add_argument("--tp1", type=float, default=0.02)
    p.add_argument("--tp2", type=float, default=0.02)
    p.add_argument("--sl",  type=float, default=-0.01)
    p.add_argument("--oco-on-holdings", action="store_true")
    p.add_argument("--oco-fallback", choices=["none", "prefer-tp1"], default="none")
    p.add_argument("--live", action="store_true")

    # Тайминги
    p.add_argument("--status-interval", type=int, default=2)
    p.add_argument("--loop-minutes", type=int, default=5)

    return p.parse_args()

def main() -> int:
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("[ERR] Пустой список символов.", file=sys.stderr)
        return 2

    base_script = args.base.strip() or DEFAULT_BASE
    if not os.path.exists(base_script):
        # пробуем рядом с текущим файлом
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(here, base_script)
        if os.path.exists(cand):
            base_script = cand
        else:
            print(f"[ERR] Базовый скрипт не найден: {args.base}", file=sys.stderr)
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
                # pct-генерация
                now = get_now_price(sym)
                tick, step, min_notional = get_filters(sym)

                if tick <= 0:
                    print(f"[WARN] {sym} tickSize=0 — квантуем как есть", file=sys.stderr)

                # лог ограничений биржи — удобно для дебага
                print(f"[PLAN] {sym} filters: tick={tick:.8f} step={step:.8f} minNotional={min_notional:.4f}")

                # парсим "--ladder-pct"
                try:
                    lo_s, hi_s, den_s = [x.strip() for x in args.ladder_pct.split(",")]
                    pct_low  = -abs(float(lo_s))   # вниз гарантированно отрицательный
                    pct_high =  abs(float(hi_s))   # вверх гарантированно положительный
                    density  = int(den_s) if den_s else args.grid_density
                except Exception:
                    pct_low, pct_high, density = -0.5, 20.0, args.grid_density

                # ATR-масштаб
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

                # разовая диагностика плана
                print(f"[PLAN] {sym} now≈{now:.4f} ATR_ratio≈{atr_ratio:.4f} scale={scale:.3f}")
                print(f"[PLAN] {sym} ladder -> {ladder_csv}")

                # счётчики уровней по сторонам (на основе итогового плоского списка)
                buy_cnt  = sum(1 for x in levels if x <= now)
                sell_cnt = sum(1 for x in levels if x >  now)
                print(f"[PLAN] {sym} levels: BUY={buy_cnt} SELL={sell_cnt}")

                # массивы сторон для превью (build_ladder_pct уже отдаёт BUY↓, SELL↑)
                buy_side  = [x for x in levels if x <= now]
                sell_side = [x for x in levels if x >  now]

                print(f"[PLAN] {sym} BUY preview:  {_preview_levels(buy_side)}")
                print(f"[PLAN] {sym} SELL preview: {_preview_levels(sell_side)}")

            # запуск базового скрипта
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

            # отдельный поток для стриминга логов этого подпроцесса
            t = threading.Thread(target=stream_prefixed, args=(sym, proc), daemon=True)
            t.start()
            threads.append(t)

        # ждём завершения всех подпроцессов
        for proc in procs:
            proc.wait()
        # даём тредам дочитать буферы
        for t in threads:
            t.join(timeout=1.0)

        # коды возврата
        rc = 0
        for sym, proc in zip(symbols, procs):
            code = proc.poll()
            if code is None:
                code = proc.wait()
            print(f"[DONE] {sym} → exit={code}")
            rc |= 0 if code == 0 else 1
        return rc

    except KeyboardInterrupt:
        print("\n[INTERRUPT] Остановка по Ctrl+C — завершаю подпроцессы…", file=sys.stderr)
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
