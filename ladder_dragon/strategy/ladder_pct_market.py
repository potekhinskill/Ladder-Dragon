# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve ordered public reads and percentage-ladder diagnostics.

import sys
from decimal import Decimal
from ladder_dragon.execution import tools_market as TM
from ladder_dragon.strategy.indicators import atr_sma_from_klines


def die(msg, code=2):
    print("[ERR]", msg, file=sys.stderr); sys.exit(code)


def calc_atr(symbol: str, interval: str = "1h", window: int = 14) -> float:
    """Calculate the legacy simple-average true range."""
    k = TM.get_klines(symbol, interval, limit=max(window + 2, 16))
    if not k or len(k) < 2:
        return 0.0
    return atr_sma_from_klines(k, exclude_latest=False)


def _filters_decimal(symbol: str) -> dict:
    """Handle filters decimal."""
    f = TM.get_symbol_filters(symbol)
    D = Decimal
    try:
        tick = D(str(f.get("tickSize") or "0.01"))
        if tick <= 0:
            die(f"Invalid tickSize for {symbol}: {tick}", code=6)
    except (RuntimeError, KeyError, TypeError, ValueError, ArithmeticError) as e:
        die(f"Bad filters for {symbol}: {e}", code=6)
    out = {
        "tickSize": D(str(f.get("tickSize", "0.01") or "0.01")),
        "stepSize": D(str(f.get("stepSize", "0") or "0")) if f.get("stepSize") else None,
        "minQty":   D(str(f.get("minQty", "0") or "0"))   if f.get("minQty")   else None,
        "minNotional": D(str(f.get("minNotional", "5") or "5")),
    }
    return out


def _now_price_decimal(symbol: str) -> Decimal:
    try:
        px = TM.get_ticker_price(symbol)
        return Decimal(str(px))
    except TM.BinanceHttpError as e:
        die(f"Failed to fetch ticker price: {e}")
