# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate Binance exchange filters before order submission.
"""Fail-closed helpers for Binance order filters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from ladder_dragon.execution.exchange_math import decimal


def symbol_row(exchange_info: Mapping[str, Any], symbol: str) -> Mapping[str, Any]:
    """Return exactly one matching symbol row or reject malformed metadata."""
    rows = exchange_info.get("symbols")
    if not isinstance(rows, list):
        raise RuntimeError("exchangeInfo symbols are unavailable")
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and str(row.get("symbol", "")).upper() == symbol.upper()
    ]
    if len(matches) != 1:
        raise RuntimeError(f"exchangeInfo did not return exactly one {symbol} row")
    return matches[0]


def filter_map(row: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    filters = row.get("filters")
    if not isinstance(filters, list):
        raise RuntimeError("exchangeInfo filters are unavailable")
    result: dict[str, Mapping[str, Any]] = {}
    for item in filters:
        if isinstance(item, Mapping) and item.get("filterType"):
            result[str(item["filterType"])] = item
    return result


def validate_sell_percent_prices(
    exchange_info: Mapping[str, Any],
    *,
    symbol: str,
    reference_price: object,
    prices: Iterable[object],
) -> bool:
    """Validate SELL prices against Binance percent filters when advertised.

    ``False`` means Binance did not advertise either percent filter. Malformed
    filter data and out-of-range prices raise so callers can fail closed before
    a signed mutation.
    """
    filters = filter_map(symbol_row(exchange_info, symbol))
    percent = filters.get("PERCENT_PRICE_BY_SIDE")
    if percent is not None:
        lower_multiplier = decimal(percent.get("askMultiplierDown"))
        upper_multiplier = decimal(percent.get("askMultiplierUp"))
    else:
        percent = filters.get("PERCENT_PRICE")
        if percent is None:
            return False
        lower_multiplier = decimal(percent.get("multiplierDown"))
        upper_multiplier = decimal(percent.get("multiplierUp"))

    reference = decimal(reference_price)
    if reference <= 0 or lower_multiplier <= 0 or upper_multiplier <= lower_multiplier:
        raise RuntimeError("invalid Binance percent-price filter")
    lower: Decimal = reference * lower_multiplier
    upper: Decimal = reference * upper_multiplier
    for value in prices:
        price = decimal(value)
        if price <= 0 or price < lower or price > upper:
            raise RuntimeError(
                f"SELL price {price} outside Binance percent-price range "
                f"[{lower}, {upper}]"
            )
    return True
