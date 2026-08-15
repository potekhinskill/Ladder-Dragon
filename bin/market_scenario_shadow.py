#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run one universal multi-symbol SHADOW scenario collection cycle.
"""Collect deterministic market scenarios without execution authority."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path

from ladder_dragon.market_analysis.config import (
    resolve_analysis_symbols,
    resolve_analysis_timeframes,
)
from ladder_dragon.market_analysis.runtime import MarketScenarioService


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in value.split(",") if item.strip())


def main() -> int:
    try:
        symbols = resolve_analysis_symbols(
            os.getenv("BOT_MARKET_ANALYSIS_SYMBOLS", "SOLUSDT,ETHUSDT,BTCUSDT")
        )
        timeframes = resolve_analysis_timeframes(
            os.getenv("BOT_MARKET_ANALYSIS_TIMEFRAMES", "1h,4h,1d,1w,1M")
        )
        round_trip_cost = Decimal(
            os.getenv("BOT_MARKET_ANALYSIS_ROUND_TRIP_COST_PCT", "0.0025")
        )
    except (InvalidOperation, ValueError) as exc:
        print(json.dumps({
            "status": "BLOCKED", "error_type": type(exc).__name__
        }, sort_keys=True))
        return 2
    service = MarketScenarioService(
        database=Path(os.getenv(
            "BOT_MARKET_ANALYSIS_DB", "db/market_scenario_shadow.sqlite3"
        )),
        status_file=Path(os.getenv(
            "BOT_MARKET_ANALYSIS_STATUS_FILE",
            "/var/lib/ladder-dragon/market-analysis/status.json",
        )),
        base_url=os.getenv("BINANCE_API_BASE", "https://api.binance.com"),
        symbols=symbols,
        timeframes=timeframes,
        execution_symbols=_csv(os.getenv("BOT_SERVICE_SYMBOLS", "SOLUSDT")),
        round_trip_cost_pct=round_trip_cost,
    )
    report = service.run_once()
    print(json.dumps({
        "status": report["status"],
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "apply_allowed": False,
    }, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
