# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own read-only trade history HTTP handlers.
"""Read-only trade history HTTP handlers with live dependencies."""

import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import List
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ladder_dragon.dashboard.history_dependencies import HistoryRouteState
from ladder_dragon.dashboard.history_reader import select_filled_orders


def build_history_router(state: HistoryRouteState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/trades/symbols")
    def trades_symbols(hours: int = 168):
        """Handle trades symbols."""
        hours = int(hours)
        cutoff = int(state.time.time()) - max(0, hours) * 3600 if hours > 0 else 0
        try:
            con, _ = state._open_db()
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
            print(f"[DASHBOARD] DB_OPEN_FAILED type={type(exc).__name__}", flush=True)
            return state._database_unavailable_response()
        try:
            if hours > 0:
                sql = """
              SELECT DISTINCT symbol
              FROM trades
              WHERE (CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END) >= ?
              ORDER BY symbol
            """
                rows = con.execute(sql, (cutoff,)).fetchall()
            else:
                sql = "SELECT DISTINCT symbol FROM trades ORDER BY symbol"
                rows = con.execute(sql).fetchall()
            syms = [r["symbol"] for r in rows if r["symbol"]]
            return JSONResponse({"ok": True, "symbols": syms})
        finally:
            try: con.close()
            except sqlite3.Error: pass

    @router.get("/api/trades/recent")
    def trades_recent(limit: int = 20, symbols: str = ""):
        limit = max(1, min(int(limit), 5000))
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
        try:
            con, path = state._open_db()
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
            print(f"[DASHBOARD] DB_OPEN_FAILED type={type(exc).__name__}", flush=True)
            return state._database_unavailable_response()
        try:
            sym_filter = ""
            args: List = []
            if syms:
                qs = ",".join("?" for _ in syms)
                sym_filter = f" AND symbol IN ({qs})"
                args.extend(syms)
            sql = f"""
        SELECT symbol, side, price_text AS price, gross_qty_text AS qty,
               COALESCE(commission_quote_text, '0') AS fee_quote,
               CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
        FROM trades_exact
        WHERE 1=1 {sym_filter}
        ORDER BY ts_s DESC
        LIMIT ?
        """
            args.append(limit)
            rows = [dict(r) for r in con.execute(sql, args).fetchall()]
            for r in rows:
                r["price"] = float(Decimal(str(r["price"])))
                r["qty"] = float(Decimal(str(r["qty"])))
                r["fee_quote"] = float(Decimal(str(r["fee_quote"])))
                r["time"] = datetime.fromtimestamp(int(r["ts_s"]), state.APP_TZ).strftime("%Y-%m-%d %H:%M:%S")
            return JSONResponse({"ok": True, "rows": rows})
        finally:
            try: con.close()
            except sqlite3.Error: pass

    @router.get("/api/trades/filled")
    def api_trades_filled(
        hours: int = 24, symbols: str = "", limit: int = 300, offset: int = 0
    ):
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
        items = select_filled_orders(state, hours, syms, limit, offset)
        return JSONResponse(items)

    @router.get("/api/orders/filled")
    def api_orders_filled(
        hours: int = 24, symbols: str = "", limit: int = 300, offset: int = 0
    ):
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
        items = select_filled_orders(state, hours, syms, limit, offset)
        return JSONResponse(items)

    @router.get("/api/fills")
    def api_fills(
        hours: int = 24, symbols: str = "", limit: int = 300, offset: int = 0
    ):
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
        items = select_filled_orders(state, hours, syms, limit, offset)
        return JSONResponse(items)

    return router
