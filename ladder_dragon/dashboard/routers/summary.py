# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: serve canonical trade accounting through live application dependencies.
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import sqlite3
from ladder_dragon.dashboard.summary_dependencies import SummaryRouteState


def build_summary_router(state: SummaryRouteState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/trades/summary")
    def trades_summary(hours: int = 24, symbols: str = ""):
        """
    Return trading totals and three deliberately separate accounting measures.

    ``cashflow_pnl_usdt`` is sells minus buys minus fees. ``net_pnl_usdt`` and
    ``realized_pnl_usdt`` are identical FIFO realized trading PnL after BUY and
    SELL fees. ``portfolio_change_usdt`` and ``equity_pnl_usdt`` are the
    mark-to-market portfolio value change and must not be presented as bot
    earnings. Equity uses Binance balances and historical/current prices, with
    an explicit approximation fallback.
    """
        hours = max(1, min(int(hours), 168))
        end_s = int(state.time.time())
        cutoff_s = end_s - hours * 3600
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None

        try:
            con, path = state._open_db()
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
            print(f"[DASHBOARD] DB_OPEN_FAILED type={type(exc).__name__}", flush=True)
            return state._database_unavailable_response()

        fee_pct = state._fee_pct_default()
        try:
            rows = state._load_trades(con, syms)
            stats = state._fifo_realized_pnl(rows, cutoff_s, fee_pct, end_s=end_s)
            # Remote portfolio valuation must not delay local trade accounting.
            # Return cached equity now and refresh it in one bounded background job.
            eq, cache_status, cache_age = state._EQUITY_SUMMARY_CACHE.get(
                (hours, tuple(syms or ())),
                lambda: state.equity_pnl_usdt(cutoff_s, list(rows), fee_pct, syms),
            )
            if eq is None:
                eq = {
                    "method": cache_status,
                    "equity_now_usdt": None,
                    "equity_then_usdt": None,
                    "equity_pnl_usdt": None,
                    "equity_pct": None,
                    "equity_assets": None,
                }
            eq["equity_cache_status"] = cache_status
            eq["equity_cache_age_sec"] = (
                round(cache_age, 3) if cache_age is not None else None
            )

            equity_then = eq.get("equity_then_usdt")
            equity_pnl  = eq.get("equity_pnl_usdt")
            equity_pct  = eq.get("equity_pct")
            if equity_pct is None and (equity_then not in (None, 0)) and (equity_pnl is not None) and abs(equity_then) >= 10.0:
                try:
                    equity_pct = round((equity_pnl / equity_then) * 100.0, 2)
                except (ArithmeticError, TypeError, ValueError):
                    equity_pct = None

            return JSONResponse({
                "ok": True,
                "hours": hours,
                "symbols": "" if not syms else ",".join(syms),
                "total_trades": stats["total_trades"],
                "buy_volume_usdt": stats["buy_volume_usdt"],
                "sell_volume_usdt": stats["sell_volume_usdt"],
                "fees_usdt": stats["fees_usdt"],
                "cashflow_pnl_usdt": stats["cashflow_pnl_usdt"],
                "realized_pnl_usdt": stats["realized_pnl_usdt"],
                "net_pnl_usdt": stats["realized_pnl_usdt"],
                "realized_pnl_method": (
                    "unavailable-incomplete-fifo-history"
                    if stats.get("realized_pnl_status", "exact") != "exact"
                    else "fifo-net-fees"
                ),
                "realized_pnl_status": stats.get("realized_pnl_status", "exact"),
                "realized_pnl_excluded_symbols": stats.get(
                    "realized_pnl_excluded_symbols", []
                ),
                "portfolio_change_usdt": eq["equity_pnl_usdt"],
                "equity_pnl_usdt": eq["equity_pnl_usdt"],
                "equity_now_usdt": eq.get("equity_now_usdt"),
                "equity_now_usdt_approx": eq.get("equity_now_usdt_approx"),
                "equity_then_usdt": equity_then,
                "equity_pct": equity_pct,
                "equity_method": eq.get("method"),
                "equity_assets": eq.get("equity_assets"),
                "equity_cache_status": eq.get("equity_cache_status"),
                "equity_cache_age_sec": eq.get("equity_cache_age_sec"),
            })
        finally:
            try: con.close()
            except sqlite3.Error: pass

    return router
