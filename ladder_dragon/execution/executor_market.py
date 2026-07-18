# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: implement the executor market component of the execution layer.
"""Рыночные и аккаунтные чтения, используемые символьным исполнителем."""

from __future__ import annotations

from typing import Any, Callable, Dict, MutableMapping, Tuple


def get_price(
    symbol: str,
    *,
    public_get: Callable[..., Any],
    logger: Callable[[str], None],
) -> float:
    """Получить цену через ticker → midpoint стакана → average-price fallback."""
    try:
        payload = public_get("/api/v3/ticker/price", {"symbol": symbol})
        if isinstance(payload, dict) and "price" in payload:
            return float(payload["price"])
        return float(payload[0]["price"])
    except Exception as ticker_error:
        logger(
            f"[ERR] {symbol}: {ticker_error} at /ticker/price, "
            "trying /ticker/bookTicker"
        )
        try:
            payload = public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
            bid = float(payload["bidPrice"])
            ask = float(payload["askPrice"])
            return (bid + ask) / 2.0 if ask > 0 else bid
        except Exception as book_error:
            logger(
                f"[ERR] {symbol}: {book_error} at /ticker/bookTicker, "
                "trying /avgPrice"
            )
            payload = public_get("/api/v3/avgPrice", {"symbol": symbol})
            return float(payload["price"])


def get_balances(
    *,
    signed_request: Callable[..., Any],
) -> Dict[str, Dict[str, float]]:
    """Вернуть свободные и заблокированные балансы по каждому активу."""
    payload = signed_request("GET", "/api/v3/account")
    balances: Dict[str, Dict[str, float]] = {}
    for row in payload.get("balances", []):
        balances[row.get("asset")] = {
            "free": float(row.get("free", 0)),
            "locked": float(row.get("locked", 0)),
        }
    return balances


def get_symbol_assets(
    symbol: str,
    *,
    exchange_info: Callable[[str], Any],
    cache: MutableMapping[str, Tuple[str, str]],
) -> Tuple[str, str]:
    """Определить base/quote через exchangeInfo с консервативным fallback."""
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
    except Exception:
        pass
    if normalized.endswith("USDT"):
        return normalized[:-4], "USDT"
    return normalized[:-4], normalized[-4:]
