# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate exact requested prices from a bounded public ticker response.
"""Validate a public ticker collection without inferring missing markets."""

from decimal import Decimal, InvalidOperation


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
