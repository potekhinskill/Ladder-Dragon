# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own read-only trading dashboard endpoint implementations.
"""Read-model routes retain current readers and stale-response policy."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ladder_dragon.dashboard.trading_dependencies import TradingRouteState


def build_trading_router(state: TradingRouteState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/trading/overview")
    def trading_overview():
        try:
            return JSONResponse(state.trading_overview_snapshot())
        except state._DATA_SOURCE_ERRORS as exc:
            print(f"[DASHBOARD] TRADING_OVERVIEW_FAILED type={type(exc).__name__}", flush=True)
            return JSONResponse({"ok": False, "error": "TRADING_OVERVIEW_FAILED"}, status_code=503)


    @router.get("/api/account/balances")
    def account_balances():
        """Handle account balances."""
        try:
            return JSONResponse(state.account_balances_snapshot())
        except state._DATA_SOURCE_ERRORS as exc:
            print(f"[DASHBOARD] ACCOUNT_BALANCE_FAILED type={type(exc).__name__}", flush=True)
            fallback = state._stale_binance_snapshot(
                state._BALANCE_CACHE,
                state._BALANCE_CACHE_LOCK,
                "ACCOUNT_BALANCE_STALE",
            )
            if fallback is not None:
                return JSONResponse(
                    fallback,
                    headers={"Warning": '110 - "stale Binance balance snapshot"'},
                )
            return JSONResponse({"ok": False, "error": "ACCOUNT_BALANCE_FAILED"}, status_code=503)


    @router.get("/api/account/open-orders")
    def account_open_orders():
        """Handle account open orders."""
        try:
            return JSONResponse(state.account_open_orders_snapshot())
        except state._DATA_SOURCE_ERRORS as exc:
            print(f"[DASHBOARD] OPEN_ORDERS_FAILED type={type(exc).__name__}", flush=True)
            fallback = state._stale_binance_snapshot(
                state._OPEN_ORDERS_CACHE,
                state._OPEN_ORDERS_CACHE_LOCK,
                "OPEN_ORDERS_STALE",
            )
            if fallback is not None:
                return JSONResponse(
                    fallback,
                    headers={"Warning": '110 - "stale Binance open-orders snapshot"'},
                )
            return JSONResponse({"ok": False, "error": "OPEN_ORDERS_FAILED"}, status_code=503)


    @router.get("/api/market/scenarios")
    def market_scenarios(): return state.market_analysis_snapshot()

    return router
