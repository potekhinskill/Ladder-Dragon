#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: inspect stored trade statistics.

import os, sys, argparse, sqlite3, time
from decimal import Decimal
from typing import List

# tools_stats.py — project statistics module.
try:
    from ladder_dragon.execution import tools_stats as ts
except ImportError:
    print("tools_stats.py was not found. Run this command from the bot directory.", file=sys.stderr)
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
    print("\n=== Inventory (qty, avg_price, realized_pnl) ===")
    for s in symbols:
        try:
            qty, avg_price, realized = ts.get_inventory_decimal(con, s)
            print(f"{s:10s}  qty={qty:.10f}  avg={avg_price:.8f}  realized_pnl={realized:.2f}")
        except (sqlite3.Error, ArithmeticError, TypeError, ValueError) as e:
            print(f"{s:10s}  <no data> ({e})")

def print_last_trades(con: sqlite3.Connection, symbols: List[str], limit: int, utc: bool) -> None:
    cur = con.cursor()
    print(f"\n=== Recent trades by symbol (limit={limit}) ===")
    for s in symbols:
        print(f"\n-- {s} --")
        q = f"""
            SELECT {ts_expr(utc)} AS ts_str,
                symbol, side,
                gross_qty_text, price_text, commission_quote_text
            FROM trades_exact
            WHERE symbol=?
            ORDER BY ts DESC
            LIMIT ?;
        """
        try:
            rows = cur.execute(q, (s, limit)).fetchall()
            if not rows:
                print("  (empty)")
                continue
            for dt, sym, side, qty, price, fee in rows:
                qty_d = Decimal(str(qty))
                price_d = Decimal(str(price))
                fee_text = "unpriced" if fee is None else f"{Decimal(str(fee)):.6f}"
                print(
                    f"  {dt}  {str(side):<4s}  qty={qty_d:.10f}  "
                    f"price={price_d:.8f}  fee_q={fee_text}"
                )
        except (sqlite3.Error, ArithmeticError, TypeError, ValueError) as e:
            print("  error:", e)

def print_daily_monthly(con: sqlite3.Connection, symbols: List[str], utc: bool) -> None:
    tm = time.gmtime() if utc else time.localtime()
    year, month = tm.tm_year, tm.tm_mon
    print(f"\n=== Summaries: day (today) and month ({year:04d}-{month:02d}) ===")
    for s in symbols:
        try:
            # Support both signatures.
            try:
                day = ts.daily_summary(con, s, utc=utc)
            except TypeError:
                day = ts.daily_summary(con, s)
        except (sqlite3.Error, ArithmeticError, TypeError, ValueError) as e:
            day = {"error": str(e)}

        try:
            # Pass UTC support through the module when monthly_summary requires it.
            mon = ts.monthly_summary(con, s, year, month)
        except (sqlite3.Error, ArithmeticError, TypeError, ValueError) as e:
            mon = {"error": str(e)}

        print(f"\n-- {s} --")
        print("daily :", day)
        print("monthly:", mon)

def print_global_last(con: sqlite3.Connection, limit: int, utc: bool) -> None:
    print(f"\n=== Latest {limit} trades across all symbols ===")
    q = f"""
        SELECT {ts_expr(utc)} AS ts_str,
            symbol, side,
            gross_qty_text, price_text, commission_quote_text
        FROM trades_exact
        ORDER BY ts DESC
        LIMIT ?;
    """
    cur = con.cursor()
    try:
        for dt, sym, side, qty, price, fee in cur.execute(q, (limit,)):
            qty_d = Decimal(str(qty))
            price_d = Decimal(str(price))
            fee_text = "unpriced" if fee is None else f"{Decimal(str(fee)):.6f}"
            print(
                f"  {dt}  {sym:10s} {str(side):<4s} qty={qty_d:.10f} "
                f"price={price_d:.8f} fee_q={fee_text}"
            )
    except (sqlite3.Error, ArithmeticError, TypeError, ValueError) as e:
        print("  error:", e)

def main():
    ap = argparse.ArgumentParser(
        description="Inspect bot statistics stored in SQLite",
        epilog=(
            "Examples:\n"
            "  python3 bin/stats_view.py --utc --limit 5\n"
            "  python3 bin/stats_view.py --symbols SOLUSDT,ETHUSDT --global-limit 50\n"
            "  BOT_STATS_DB=/path/bot_stats.db python3 bin/stats_view.py\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--db", default=env_default_db(), help="database path; defaults to BOT_STATS_DB or ~/apps/binance_bot/db/bot_stats.db")
    ap.add_argument("--symbols", default="", help="comma-separated list; defaults to symbols found in trades")
    ap.add_argument("--limit", type=int, default=10, help="number of recent trades shown per symbol")
    ap.add_argument("--global-limit", type=int, default=20, help="number of recent trades shown in the combined feed")
    ap.add_argument("--utc", action="store_true", help="show UTC timestamps instead of local time")
    args = ap.parse_args()

    db = os.path.expanduser(args.db)
    if not os.path.exists(db):
        print("Database not found:", db, file=sys.stderr)
        sys.exit(2)

    con = ts.connect_ro(db)

    if args.symbols.strip():
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = detect_symbols(con)

    if not symbols:
        print("No symbols found because the trades table is empty or missing.", file=sys.stderr)
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
