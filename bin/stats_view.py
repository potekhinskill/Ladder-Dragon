#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: inspect stored trade statistics.

import os, sys, argparse, sqlite3, time
from typing import List

# tools_stats.py — project statistics module.
try:
    from ladder_dragon.execution import tools_stats as ts
except Exception:
    print("Не найден tools_stats.py рядом. Запустите из каталога бота.", file=sys.stderr)
    raise

def env_default_db() -> str:
    return os.getenv("BOT_STATS_DB", "/home/bot/apps/binance_bot/db/bot_stats.db")

def detect_symbols(con: sqlite3.Connection) -> List[str]:
    cur = con.cursor()
    try:
        rows = cur.execute("SELECT DISTINCT symbol FROM trades ORDER BY 1;").fetchall()
        return [r[0] for r in rows]
    except sqlite3.OperationalError:
        return []

def ts_expr(utc: bool) -> str:
    tail = "'unixepoch','utc'" if utc else "'unixepoch','localtime'"
    # >1e14 means microseconds, >1e12 milliseconds, otherwise seconds.
    return (
        "datetime(CASE "
        "WHEN ts>1e14 THEN ts/1000000 "
        "WHEN ts>1e12 THEN ts/1000 "
        "ELSE ts END," + tail + ")"
    )

def print_inventory(con: sqlite3.Connection, symbols: List[str]) -> None:
    print("\n=== Инвентарь (qty, avg_price, realized_pnl) ===")
    for s in symbols:
        try:
            qty, avg_price, realized = ts.get_inventory(con, s)
            qty = 0.0 if qty is None else qty
            avg_price = 0.0 if avg_price is None else avg_price
            realized = 0.0 if realized is None else realized
            print(f"{s:10s}  qty={qty:.10f}  avg={avg_price:.8f}  realized_pnl={realized:.2f}")
        except Exception as e:
            print(f"{s:10s}  <нет данных> ({e})")

def print_last_trades(con: sqlite3.Connection, symbols: List[str], limit: int, utc: bool) -> None:
    cur = con.cursor()
    print(f"\n=== Последние сделки (по каждому символу, limit={limit}) ===")
    for s in symbols:
        print(f"\n-- {s} --")
        q = f"""
            SELECT {ts_expr(utc)} AS ts_str,
                symbol, side,
                CAST(COALESCE(qty,0.0)       AS REAL) AS qty,
                CAST(COALESCE(price,0.0)     AS REAL) AS price,
                CAST(COALESCE(fee_quote,0.0) AS REAL) AS fee_quote
            FROM trades
            WHERE symbol=?
            ORDER BY trades.ts DESC
            LIMIT ?;
        """
        try:
            rows = cur.execute(q, (s, limit)).fetchall()
            if not rows:
                print("  (пусто)")
                continue
            for dt, sym, side, qty, price, fee in rows:
                print(f"  {dt}  {str(side):<4s}  qty={qty:.10f}  price={price:.8f}  fee_q={fee:.6f}")
        except Exception as e:
            print("  ошибка:", e)

def print_daily_monthly(con: sqlite3.Connection, symbols: List[str], utc: bool) -> None:
    tm = time.gmtime() if utc else time.localtime()
    year, month = tm.tm_year, tm.tm_mon
    print(f"\n=== Сводки: day (сегодня) и month ({year:04d}-{month:02d}) ===")
    for s in symbols:
        try:
            # Support both signatures.
            try:
                day = ts.daily_summary(con, s, utc=utc)
            except TypeError:
                day = ts.daily_summary(con, s)
        except Exception as e:
            day = {"error": str(e)}

        try:
            # Pass UTC support through the module when monthly_summary requires it.
            mon = ts.monthly_summary(con, s, year, month)
        except Exception as e:
            mon = {"error": str(e)}

        print(f"\n-- {s} --")
        print("daily :", day)
        print("monthly:", mon)

def print_global_last(con: sqlite3.Connection, limit: int, utc: bool) -> None:
    print(f"\n=== Последние {limit} сделок по всем символам ===")
    q = f"""
        SELECT {ts_expr(utc)} AS ts_str,
            symbol, side,
            CAST(COALESCE(qty,0.0)       AS REAL) AS qty,
            CAST(COALESCE(price,0.0)     AS REAL) AS price,
            CAST(COALESCE(fee_quote,0.0) AS REAL) AS fee_quote
        FROM trades
        ORDER BY trades.ts DESC
        LIMIT ?;
    """
    cur = con.cursor()
    try:
        for dt, sym, side, qty, price, fee in cur.execute(q, (limit,)):
            print(f"  {dt}  {sym:10s} {str(side):<4s} qty={qty:.10f} price={price:.8f} fee_q={fee:.6f}")
    except Exception as e:
        print("  ошибка:", e)

def main():
    ap = argparse.ArgumentParser(
        description="Просмотр статистики бота из SQLite",
        epilog=(
            "Примеры:\n"
            "  python3 bin/stats_view.py --utc --limit 5\n"
            "  python3 bin/stats_view.py --symbols SOLUSDT,ETHUSDT --global-limit 50\n"
            "  BOT_STATS_DB=/path/bot_stats.db python3 bin/stats_view.py\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--db", default=env_default_db(), help="путь к БД (по умолчанию BOT_STATS_DB или ~/apps/binance_bot/db/bot_stats.db)")
    ap.add_argument("--symbols", default="", help="список через запятую (если не задан — авто из trades)")
    ap.add_argument("--limit", type=int, default=10, help="сколько последних сделок показывать по каждому символу")
    ap.add_argument("--global-limit", type=int, default=20, help="сколько последних сделок показать общей лентой")
    ap.add_argument("--utc", action="store_true", help="показывать время в UTC (по умолчанию — локальное)")
    args = ap.parse_args()

    db = os.path.expanduser(args.db)
    if not os.path.exists(db):
        print("БД не найдена:", db, file=sys.stderr)
        sys.exit(2)

    con = ts.connect_ro(db)

    if args.symbols.strip():
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = detect_symbols(con)

    if not symbols:
        print("Символы не найдены (таблица trades пуста или отсутствует).", file=sys.stderr)
        con.close()
        sys.exit(3)

    print(f"DB: {db}")
    print("Symbols:", ", ".join(symbols))

    print_inventory(con, symbols)
    print_last_trades(con, symbols, args.limit, args.utc)
    print_global_last(con, args.global_limit, args.utc)
    print_daily_monthly(con, symbols, args.utc)

    con.close()

if __name__ == "__main__":
    main()
