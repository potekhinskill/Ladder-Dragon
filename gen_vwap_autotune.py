#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""
Автоматический тюнер VWAP-параметров на основе статистики (tools_stats).

Сценарий:
    python gen_vwap_autotune.py --symbols SOLUSDT,ETHUSDT --hours 24 --pnl-threshold 30

Выводит строки BUY_VWAP_PREMIUM_MAP, BUY_VWAP_DISCOUNT_MAP, BUY_VWAP_DISCOUNT_SCALE_MAP,
которые можно добавить в /run/mybot/dynamic.env (перед основным запуском супервизора).

Методика (упрощённо):
    • Получаем суммарный PnL/количество сделок за последние N часов.
    • Если PnL по символу < -threshold → расширяем премию (более консервативно) и снижаем scale.
    • Если PnL > threshold → уменьшаем премию (агрессивнее) и увеличиваем scale.
    • Разумные пределы задаются аргументами, результаты сглаживаются EMA-коэффициентом.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import time

from ladder_dragon.execution.trade_accounting import TradeExecution, replay_average_cost
from db_migrate import migrate


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def fmt_map(data: Dict[str, float], precision: int) -> str:
    return ",".join(f"{sym}:{val:.{precision}f}" for sym, val in sorted(data.items()))


def ema(prev: Optional[float], new: float, alpha: float) -> float:
    if prev is None:
        return new
    return prev * (1.0 - alpha) + new * alpha


def load_prev_values(path: Optional[str]) -> Dict[str, Dict[str, float]]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception:
        return {}
    return {}


def save_values(path: Optional[str], values: Dict[str, Dict[str, float]]) -> None:
    if not path:
        return
    tmp = Path(path + ".tmp")
    dst = Path(path)
    try:
        tmp.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(dst)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def compute_fifo_pnl(rows: Iterable[Tuple[str, float, float, float]]) -> float:
    inv = 0.0
    avg = 0.0
    realized = 0.0
    for side, price, qty, fee in rows:
        price = float(price)
        qty = float(qty)
        fee = float(fee)
        if side == "BUY":
            new_inv = inv + qty
            avg = (avg * inv + price * qty + fee) / max(new_inv, 1e-12)
            inv = new_inv
        else:
            qty_eff = min(qty, inv) if inv > 0 else 0.0
            realized += (price - avg) * qty_eff - fee
            inv -= qty_eff
            if inv <= 1e-12:
                inv = 0.0
                avg = 0.0
    return realized


def get_stats(symbol: str,
              conn: sqlite3.Connection,
              hours: int) -> Tuple[float, int]:
    """Calculate window PnL using cost basis from the complete history.

    Replaying only the last N hours makes a position opened earlier look like
    a zero-cost position and can invert the tuning decision.
    """
    cutoff_ms = int((time.time() - hours * 3600) * 1000)
    rows = conn.execute(
        """
        SELECT ts, side,
               COALESCE(NULLIF(price_text, ''), CAST(price AS TEXT)),
               COALESCE(NULLIF(gross_qty, ''), CAST(qty AS TEXT)),
               COALESCE(NULLIF(net_qty, ''), CAST(qty AS TEXT)),
               commission_asset, commission_amount,
               CASE WHEN commission_value_status='unpriced' THEN NULL
                    ELSE COALESCE(NULLIF(commission_quote, ''), CAST(fee_quote AS TEXT)) END,
               COALESCE(NULLIF(commission_value_status, ''), 'legacy')
        FROM trades WHERE symbol=? AND ts<=? ORDER BY ts, id
        """,
        (symbol.upper(), int(time.time() * 1000)),
    ).fetchall()
    executions: list[TradeExecution] = []
    timestamps: list[int] = []
    for row in rows:
        try:
            executions.append(TradeExecution.create(
                symbol=symbol, side=row[1], price=row[2], gross_qty=row[3],
                net_qty=row[4], commission_asset=row[5] or "",
                commission_amount=row[6] or 0, commission_quote=row[7],
                commission_value_status=row[8] or "legacy",
            ))
            timestamps.append(int(row[0]))
        except (ArithmeticError, TypeError, ValueError):
            continue
    result = replay_average_cost(executions, allow_unpriced=False)
    sell_results = iter(result.sell_results)
    window_pnl = 0
    recent_count = 0
    for execution, timestamp in zip(executions, timestamps):
        if timestamp >= cutoff_ms:
            recent_count += 1
        if execution.side == "SELL":
            pnl = next(sell_results)
            if timestamp >= cutoff_ms:
                window_pnl += pnl
    return float(window_pnl), recent_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--pnl-threshold", type=float, default=25.0,
                        help="USDT PnL threshold to adjust more aggressively")
    parser.add_argument("--min-trades", type=int, default=20,
                        help="Minimum recent executions before tuning")
    parser.add_argument("--alpha", type=float, default=0.6,
                        help="EMA smoothing for new values")
    parser.add_argument("--precision", type=int, default=6)

    parser.add_argument("--base-premium", type=float, default=0.0030)
    parser.add_argument("--base-discount", type=float, default=0.0060)
    parser.add_argument("--base-scale", type=float, default=1.30)

    parser.add_argument("--premium-loss-mult", type=float, default=1.20)
    parser.add_argument("--premium-profit-mult", type=float, default=0.80)
    parser.add_argument("--premium-floor", type=float, default=0.0005)
    parser.add_argument("--premium-ceil", type=float, default=0.0100)

    parser.add_argument("--scale-loss-mult", type=float, default=0.80)
    parser.add_argument("--scale-profit-mult", type=float, default=1.20)
    parser.add_argument("--scale-min", type=float, default=0.8)
    parser.add_argument("--scale-max", type=float, default=3.0)

    parser.add_argument("--discount-min", type=float, default=0.0)
    parser.add_argument("--discount-max", type=float, default=0.0200)

    parser.add_argument("--state-file", type=str, default=None,
                        help="JSON file to store previous tuned values (optional)")
    parser.add_argument("--stats-db", type=str, default=None,
                        help="Path to SQLite stats DB (defaults to TS.BOT_STATS_DB or env)")

    args = parser.parse_args()

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
    discount_map: Dict[str, float] = {}
    scale_map: Dict[str, float] = {}

    for symbol in symbols:
        pnl, trade_cnt = get_stats(symbol, conn, args.hours)

        base_premium = prev_values.get(symbol, {}).get("premium", args.base_premium)
        base_discount = prev_values.get(symbol, {}).get("discount", args.base_discount)
        base_scale = prev_values.get(symbol, {}).get("scale", args.base_scale)

        premium = base_premium
        discount = base_discount
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
        discount = clamp(discount, args.discount_min, args.discount_max)
        scale = clamp(scale, args.scale_min, args.scale_max)

        prev = prev_values.get(symbol, {})
        premium_smooth = ema(prev.get("premium"), premium, args.alpha)
        discount_smooth = ema(prev.get("discount"), discount, args.alpha)
        scale_smooth = ema(prev.get("scale"), scale, args.alpha)

        premium_map[symbol] = premium_smooth
        discount_map[symbol] = discount_smooth
        scale_map[symbol] = scale_smooth

        prev_values[symbol] = {
            "premium": premium_smooth,
            "discount": discount_smooth,
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


if __name__ == "__main__":
    main()
