# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own asset groups used by exact portfolio risk valuation.
"""Canonical asset groups for portfolio valuation policy."""


STABLE_VALUATION_ASSETS = frozenset(
    {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"}
)
RISK_CONVERSION_QUOTE_ASSETS = ("USDC", "FDUSD", "BTC", "ETH")
