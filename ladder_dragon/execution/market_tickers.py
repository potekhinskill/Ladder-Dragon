# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate exact requested prices from a bounded public ticker response.
"""Validate a public ticker collection without inferring missing markets."""

from decimal import Decimal, InvalidOperation

from ladder_dragon.risk.asset_policy import RISK_CONVERSION_QUOTE_ASSETS, STABLE_VALUATION_ASSETS


def requested_prices(payload, symbols):
    """Return only requested observations; an omitted symbol proves no absence."""
    message = "invalid batch ticker response"
    wanted = set(symbols)
    if not isinstance(payload, list) or len(payload) > 10000:
        raise ValueError(message)
    result, seen = {}, set()
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError(message)
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol or len(symbol) > 128:
            raise ValueError(message)
        if symbol in seen:
            raise ValueError(message)
        seen.add(symbol)
        if symbol not in wanted:
            continue
        raw = row.get("price")
        if not isinstance(raw, str) or len(raw) > 128:
            raise ValueError(message)
        try:
            price = Decimal(raw)
        except InvalidOperation:
            raise ValueError(message) from None
        if not price.is_finite() or price <= 0:
            raise ValueError(message)
        result[symbol] = price
    return result


def valuation_prices(payload, symbols):
    """Keep current conversion observations only for omitted direct quotes."""
    wanted = set(symbols)
    result = requested_prices(payload, wanted)
    missing = wanted.difference(result)
    cross = {f"{symbol[:-4]}{quote}" for symbol in missing for quote in RISK_CONVERSION_QUOTE_ASSETS}
    result.update(requested_prices(payload, cross))
    bridges = {
        f"{quote}USDT" for quote in RISK_CONVERSION_QUOTE_ASSETS
        if quote not in STABLE_VALUATION_ASSETS
        and any(f"{symbol[:-4]}{quote}" in result for symbol in missing)
    }
    result.update(requested_prices(payload, bridges))
    return result
