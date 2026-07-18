#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: report realized 24-hour PnL.

"""
pnl_24h.py — PnL за окно (по умолчанию 24h), НЕТТО (с вычетом fee_quote).

Методы:
  - cash (по умолчанию): Денежный поток в котируемой валюте (USDT):
        Σ(SELL qty*price) − Σ(BUY qty*price) − Σ(fee_quote)
    Не требует полной истории и корректен при неполной БД.

  - realized: Разница реализованной прибыли между t1 и t0 по средневзвешенной
    себестоимости. Требует полной истории до t0. Если история не полная —
    результат будет искажен. Используй только если уверен в полноте БД.

Новые БД используют точные gross/net quantity и метаданные комиссии. Старые
таблицы с price/qty/fee_quote продолжают поддерживаться.
"""

import os
import sys
import argparse
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext

from ladder_dragon.execution.trade_accounting import TradeExecution

getcontext().prec = 28

def detect_ts_div(con: sqlite3.Connection, ts_col: str = "ts") -> int:
    cur = con.cursor()
    cur.execute(f"SELECT MIN({ts_col}), MAX({ts_col}) FROM trades")
    row = cur.fetchone()
    if not row or row[1] is None:
        return 1
    _, hi = row
    try:
        hi = int(hi)
    except Exception:
        return 1

    # Seconds are ~1e9, milliseconds ~1e12, microseconds ~1e15.
    if hi > 10_000_000_000_000:      # >1e13 → µs
        return 1_000_000
    elif hi > 10_000_000_000:        # >1e10 → ms
        return 1000
    else:
        return 1

def parse_symbols(s: str | None):
    if not s:
        return None
    x = [t.strip().upper() for t in s.split(",") if t.strip()]
    return x or None


def _accounting_columns(con: sqlite3.Connection) -> str:
    columns = {str(row[1]) for row in con.execute("PRAGMA table_info(trades)")}
    exact = {
        "price_text", "gross_qty", "net_qty", "commission_asset",
        "commission_amount", "commission_quote", "commission_value_status",
    }.issubset(columns)
    if exact:
        return """
            COALESCE(NULLIF(price_text, ''), CAST(price AS TEXT)) AS price_value,
            COALESCE(NULLIF(gross_qty, ''), CAST(qty AS TEXT)) AS gross_value,
            COALESCE(NULLIF(net_qty, ''), CAST(qty AS TEXT)) AS net_value,
            COALESCE(commission_asset, '') AS commission_asset,
            COALESCE(NULLIF(commission_amount, ''), '0') AS commission_amount,
            CASE WHEN commission_value_status = 'unpriced' THEN NULL
                 ELSE COALESCE(commission_quote, CAST(fee_quote AS TEXT)) END AS commission_quote,
            COALESCE(NULLIF(commission_value_status, ''), 'legacy') AS commission_status
        """
    return """
        CAST(price AS TEXT) AS price_value,
        CAST(qty AS TEXT) AS gross_value,
        CAST(qty AS TEXT) AS net_value,
        '' AS commission_asset,
        '0' AS commission_amount,
        CAST(COALESCE(fee_quote, 0) AS TEXT) AS commission_quote,
        'legacy' AS commission_status
    """


def _execution(row: sqlite3.Row) -> TradeExecution:
    return TradeExecution.create(
        symbol=row["symbol"],
        side=row["side"],
        price=row["price_value"],
        gross_qty=row["gross_value"],
        net_qty=row["net_value"],
        commission_asset=row["commission_asset"],
        commission_amount=row["commission_amount"],
        commission_quote=row["commission_quote"],
        commission_value_status=row["commission_status"],
    )

def fetch_trades(con: sqlite3.Connection, t0_ts: int, t1_ts: int, symbols=None):
    """Выборка сделок в окне [t0_ts, t1_ts] с дедупом (trade_id или fallback)."""
    params = [t0_ts, t1_ts]
    where = ["ts >= ? AND ts <= ?"]
    if symbols:
        ph = ",".join(["?"] * len(symbols))
        where.append(f"symbol IN ({ph})")
        params.extend(symbols)

    sql = f"""
      SELECT id, symbol, UPPER(side) AS side, {_accounting_columns(con)}, ts, trade_id
      FROM trades
      WHERE {' AND '.join(where)}
      ORDER BY ts ASC, id ASC
    """
    cur = con.execute(sql, params)

    seen_tid = set()
    seen_fallback = set()
    rows = []
    dup = 0
    for r in cur:
        tid = r["trade_id"]
        sym = r["symbol"]
        if tid is not None:
            key = (sym, int(tid))
            if key in seen_tid:
                dup += 1
                continue
            seen_tid.add(key)
        else:
            fb = (sym, r["side"], str(Decimal(str(r["price_value"]))),
                  str(Decimal(str(r["gross_value"]))), int(r["ts"]))
            if fb in seen_fallback:
                dup += 1
                continue
            seen_fallback.add(fb)
        rows.append(r)

    if dup:
        print(f"[dedup-window] skipped duplicate rows: {dup}", file=sys.stderr)
    return rows

def pnl_cash(con: sqlite3.Connection, t0_sec: int, t1_sec: int, symbols=None, ts_div: int = 1):
    """Денежный PnL за окно: Σ(SELL) − Σ(BUY) − Σ(fee). Возвращает dict по символам и сумму."""
    rows = fetch_trades(con, t0_sec * ts_div, t1_sec * ts_div, symbols)
    by_sym = {}
    for r in rows:
        s = r["symbol"]
        side = r["side"]
        if side not in ("BUY", "SELL"):
            continue
        trade = _execution(r)

        if side == "SELL":
            delta = trade.sell_proceeds_quote()
        elif side == "BUY":
            delta = -trade.buy_cost_quote()
        else:
            continue
        by_sym[s] = by_sym.get(s, Decimal("0")) + delta

    total = sum(by_sym.values(), Decimal("0"))
    return by_sym, total

# === Realized method (legacy-compatible), for complete history only ===

def iter_trades_until(con: sqlite3.Connection, t_until: int, symbols=None):
    params = [t_until]
    where = ["ts <= ?"]
    if symbols:
        ph = ",".join(["?"] * len(symbols))
        where.append(f"symbol IN ({ph})")
        params.extend(symbols)
    sql = f"""
        SELECT id, symbol, UPPER(side) as side, {_accounting_columns(con)}, ts, trade_id
        FROM trades
        WHERE {' AND '.join(where)}
        ORDER BY ts ASC, id ASC
    """
    cur = con.execute(sql, params)

    seen_tid = set()
    seen_fallback = set()
    for r in cur:
        tid = r["trade_id"]
        sym = r["symbol"]
        if tid is not None:
            key = (sym, int(tid))
            if key in seen_tid:
                continue
            seen_tid.add(key)
        else:
            fb = (sym, r["side"], str(Decimal(str(r["price_value"]))),
                  str(Decimal(str(r["gross_value"]))), int(r["ts"]))
            if fb in seen_fallback:
                continue
            seen_fallback.add(fb)
        yield r

def replay_until(con: sqlite3.Connection, t_until_sec: int, symbols=None, ts_div: int = 1):
    qty = {}; cost = {}; realized = {}
    for r in iter_trades_until(con, t_until_sec * ts_div, symbols):
        sym = r["symbol"]; side = r["side"]
        trade = _execution(r)
        q = trade.net_qty
        Q = qty.get(sym, Decimal("0")); C = cost.get(sym, Decimal("0"))

        if side == "BUY":
            qty[sym] = Q + q
            cost[sym] = C + trade.buy_cost_quote()

        elif side == "SELL":
            if Q <= 0:
                # No history: treat this as a sale without inventory.
                proceeds = trade.sell_proceeds_quote()
                realized[sym] = realized.get(sym, Decimal("0")) + proceeds
                qty[sym] = Q - q
                if realized.get(f"__warn_{sym}") is None:
                    print(f"[warn] SELL with nonpositive inventory for {sym} (history incomplete?) — treating cost as 0", file=sys.stderr)
                    realized[f"__warn_{sym}"] = Decimal("0")
                continue  # ← ВАЖНО: всегда выходим из SELL при Q<=0

            # Standard sale at average cost.
            avg = C / Q
            used = min(q, Q)
            cost_out = avg * used
            proceeds = trade.sell_proceeds_quote() * (used / q)
            pnl = proceeds - cost_out
            qty[sym] = Q - used
            cost[sym] = C - cost_out
            realized[sym] = realized.get(sym, Decimal("0")) + pnl

        else:
            # Unknown side: skip the row.
            continue

    return qty, cost, realized

def pnl_realized(con: sqlite3.Connection, t0_sec: int, t1_sec: int, symbols=None, ts_div: int = 1):
    _, _, r0 = replay_until(con, t0_sec, symbols, ts_div)
    _, _, r1 = replay_until(con, t1_sec, symbols, ts_div)

    def is_real_key(k: str) -> bool:
        return not (isinstance(k, str) and k.startswith("__warn_"))

    all_syms = {k for k in set(r0) | set(r1) if is_real_key(k)}
    by_sym = {}
    for s in all_syms:
        by_sym[s] = r1.get(s, Decimal("0")) - r0.get(s, Decimal("0"))
    total = sum(by_sym.values(), Decimal("0"))
    return by_sym, total

# === Parse --from/--to windows ===

def _parse_dt_arg(s: str | None, use_utc: bool) -> datetime | None:
    """Парсит строку даты/времени. Поддержка:
       - ISO: 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM[:SS]'
       - Если без TZ — проставляется UTC при --utc или локальный tz иначе.
    """
    if not s:
        return None
    # Try fromisoformat first.
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fallback without seconds.
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        except ValueError:
        # Date only means 00:00.
            dt = datetime.strptime(s, "%Y-%m-%d")
    tz = timezone.utc if use_utc else datetime.now().astimezone().tzinfo
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt

def main():
    ap = argparse.ArgumentParser(description="PNL за окно, нетто (с вычетом fee_quote)")
    ap.add_argument("--db", default=os.getenv("BOT_STATS_DB", "/home/bot/apps/binance_bot/db/bot_stats.db"))
    ap.add_argument("--hours", type=int, default=24, help="длительность окна, если не заданы --from/--to")
    ap.add_argument("--from", dest="from_dt", default=None, help="начало окна: 'YYYY-MM-DD[ HH:MM[:SS]]'")
    ap.add_argument("--to", dest="to_dt", default=None, help="конец окна: 'YYYY-MM-DD[ HH:MM[:SS]]' (по умолчанию: сейчас)")
    ap.add_argument("--symbols", default=None, help="CSV, напр. SOLUSDT,ETHUSDT")
    ap.add_argument("--utc", action="store_true", help="UTC вместо локального времени")
    ap.add_argument("--method", choices=["cash","realized"], default="cash", help="способ расчёта")
    ap.add_argument("--json", action="store_true", help="вывести результат в формате JSON")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}", file=sys.stderr)
        sys.exit(2)

    now = datetime.utcnow().replace(tzinfo=timezone.utc) if args.utc else datetime.now().astimezone()
    # Select the window in priority order: --from/--to, then --hours.
    to_dt = _parse_dt_arg(args.to_dt, args.utc) or now
    from_dt = _parse_dt_arg(args.from_dt, args.utc)
    if from_dt is None:
        t0, t1 = to_dt - timedelta(hours=args.hours), to_dt
    else:
        t0, t1 = from_dt, to_dt

    # Validate window-bound ordering.
    if t1 < t0:
        print("Error: 'to' раньше, чем 'from'", file=sys.stderr)
        sys.exit(2)

    # Filter by symbols.
    syms = parse_symbols(args.symbols)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        ts_div = detect_ts_div(con, "ts")
        if args.method == "cash":
            by_sym, total = pnl_cash(con, int(t0.timestamp()), int(t1.timestamp()), syms, ts_div)
            header = "PNL за окно (денежный, нетто с учетом комиссий):"
        else:
            by_sym, total = pnl_realized(con, int(t0.timestamp()), int(t1.timestamp()), syms, ts_div)
            header = "PNL за окно (реализованный по себестоимости, нетто):"

        q2 = Decimal("0.01")

        if args.json:
            payload = {
                "method": args.method,
                "window": [t0.isoformat(), t1.isoformat()],
                "symbols": {s: str(by_sym[s].quantize(q2)) for s in sorted(by_sym.keys())},
                "total": str(total.quantize(q2))
            }
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        else:
            hours_len = (t1 - t0).total_seconds() / 3600.0
            print(f"DB: {args.db}")
            print(f"Window: {t0.strftime('%Y-%m-%d %H:%M:%S')} .. {t1.strftime('%Y-%m-%d %H:%M:%S')} ({hours_len:.2f}h, {'UTC' if args.utc else 'local'})\n")
            print(header + "\n")
            for s in sorted(by_sym.keys()):
                val = by_sym[s].quantize(q2)
                print(f"  {s:10s} : {val} USDT")
            print(f"\nИТОГО: {total.quantize(q2)} USDT")
    finally:
        con.close()

if __name__ == "__main__":
    main()
