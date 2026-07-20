# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor market component of the execution layer.
"""Ladder Dragon executor market support."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Dict, MutableMapping, Tuple

import requests


MARKET_READ_ERRORS = (
    ArithmeticError,
    IndexError,
    KeyError,
    RuntimeError,
    TypeError,
    ValueError,
    requests.RequestException,
)


def _price_decimal(value: object, *, field: str) -> Decimal:
    price = Decimal(str(value))
    if not price.is_finite() or price <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return price


def get_price_decimal(
    symbol: str,
    *,
    public_get: Callable[..., Any],
    logger: Callable[[str], None],
) -> Decimal:
    """Return an exact positive market price with conservative fallbacks."""
    try:
        payload = public_get("/api/v3/ticker/price", {"symbol": symbol})
        if isinstance(payload, dict) and "price" in payload:
            return _price_decimal(payload["price"], field="ticker price")
        return _price_decimal(payload[0]["price"], field="ticker price")
    except MARKET_READ_ERRORS as ticker_error:
        logger(
            f"[ERR] {symbol}: {ticker_error} at /ticker/price, "
            "trying /ticker/bookTicker"
        )
        try:
            payload = public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
            bid = _price_decimal(payload["bidPrice"], field="best bid")
            ask = _price_decimal(payload["askPrice"], field="best ask")
            if ask < bid:
                raise ValueError("best ask is below best bid")
            return (bid + ask) / Decimal("2")
        except MARKET_READ_ERRORS as book_error:
            logger(
                f"[ERR] {symbol}: {book_error} at /ticker/bookTicker, "
                "trying /avgPrice"
            )
            payload = public_get("/api/v3/avgPrice", {"symbol": symbol})
            return _price_decimal(payload["price"], field="average price")


def get_price(
    symbol: str,
    *,
    public_get: Callable[..., Any],
    logger: Callable[[str], None],
) -> float:
    """Return a float compatibility view for indicator-only consumers."""
    return float(
        get_price_decimal(symbol, public_get=public_get, logger=logger)
    )


def get_balances(
    *,
    signed_request: Callable[..., Any],
) -> Dict[str, Dict[str, Decimal]]:
    """Return exact account balances as decimals."""
    payload = signed_request("GET", "/api/v3/account")
    balances: Dict[str, Dict[str, Decimal]] = {}
    for row in payload.get("balances", []):
        free = Decimal(str(row.get("free", "0") or "0"))
        locked = Decimal(str(row.get("locked", "0") or "0"))
        if not free.is_finite() or not locked.is_finite() or free < 0 or locked < 0:
            raise ValueError("Binance returned an invalid account balance")
        balances[row.get("asset")] = {
            "free": free,
            "locked": locked,
        }
    return balances


def get_symbol_assets(
    symbol: str,
    *,
    exchange_info: Callable[[str], Any],
    cache: MutableMapping[str, Tuple[str, str]],
) -> Tuple[str, str]:
    """Return symbol assets."""
    normalized = symbol.upper()
    cached = cache.get(normalized)
    if cached is not None:
        return cached
    try:
        payload = exchange_info(normalized)
        if isinstance(payload, dict) and payload.get("symbols"):
            row = payload["symbols"][0]
            base = str(row.get("baseAsset", "")).upper()
            quote = str(row.get("quoteAsset", "")).upper()
            if base and quote:
                cache[normalized] = (base, quote)
                return base, quote
    except MARKET_READ_ERRORS:
        # Symbol suffix inference is deliberately limited to a read-only
        # fallback. Order placement still requires exchange filters.
        pass
    if normalized.endswith("USDT"):
        return normalized[:-4], "USDT"
    return normalized[:-4], normalized[-4:]
