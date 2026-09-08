# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate exact requested prices from a bounded public ticker response.
"""Validate a public ticker collection without inferring missing markets."""

from decimal import Decimal, InvalidOperation

from ladder_dragon.risk.asset_policy import RISK_CONVERSION_QUOTE_ASSETS, STABLE_VALUATION_ASSETS


def _indexed_rows(payload):
    """Validate collection structure once, including unused duplicate rows."""
    message = "invalid batch ticker response"
    if not isinstance(payload, list) or len(payload) > 10000:
        raise ValueError(message)
    rows = {}
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError(message)
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol or len(symbol) > 128:
            raise ValueError(message)
        if symbol in rows:
            raise ValueError(message)
        rows[symbol] = row
    return rows


def _prices(rows, symbols):
    message = "invalid batch ticker response"
    result = {}
    for symbol in symbols:
        if symbol not in rows:
            continue
        raw = rows[symbol].get("price")
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


def requested_prices(payload, symbols):
    """Return only requested observations; an omitted symbol proves no absence."""
    return _prices(_indexed_rows(payload), set(symbols))


def valuation_prices(payload, symbols, *, known_prices=None):
    """Keep current conversion observations only for omitted direct quotes."""
    known = dict(known_prices or {})
    # Only validated exact observations can suppress batch value validation.
    if any(not isinstance(price, Decimal) or not price.is_finite() or price <= 0
           for price in known.values()):
        raise ValueError("invalid current snapshot price")
    wanted = set(symbols).difference(known)
    rows = _indexed_rows(payload)
    result = _prices(rows, wanted)
    missing = wanted.difference(result)
    # Once a complete route exists, lower-priority values are not required.
    for symbol in sorted(missing):
        for quote in RISK_CONVERSION_QUOTE_ASSETS:
            cross = f"{symbol[:-4]}{quote}"
            result.update(_prices(rows, {cross}.difference(known, result)))
            if cross not in result and cross not in known:
                continue
            if quote in STABLE_VALUATION_ASSETS:
                break
            bridge = f"{quote}USDT"
            result.update(_prices(rows, {bridge}.difference(known, result)))
            if bridge in result or bridge in known:
                break
    return result
