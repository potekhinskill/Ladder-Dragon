# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: provide display-only accounting helpers for dashboard read models.

"""Dashboard accounting helpers; execution decisions never import this module."""


KNOWN_QUOTES = (
    "FDUSD",
    "TUSD",
    "USDT",
    "USDC",
    "BUSD",
    "DAI",
    "BTC",
    "ETH",
    "BNB",
    "TRY",
    "EUR",
    "GBP",
    "AUD",
    "BRL",
    "JPY",
)


def base_asset_of(symbol: str) -> str:
    """Infer the base asset for a display-only Binance symbol."""
    normalized = str(symbol).upper()
    for quote in KNOWN_QUOTES:
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)]
    return normalized
