# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: seed current account valuation with one public ticker collection.
"""Disposable batch observations owned by one risk snapshot."""

from ladder_dragon.risk.asset_policy import STABLE_VALUATION_ASSETS
from ladder_dragon.risk.risk_manager import money


def seed_prices(balances, prices, reader, metrics):
    """Preserve configured prices and fetch missing direct observations once."""
    wanted = {
        f"{str(asset).upper()}USDT"
        for asset, balance in balances.items()
        if str(asset).upper() not in STABLE_VALUATION_ASSETS
        and money(balance.get("free", 0)) + money(balance.get("locked", 0)) > 0
        and f"{str(asset).upper()}USDT" not in prices
    }
    result = dict(prices)
    if len(wanted) >= 2:
        # A failed batch publishes no partial observations and primes no cache.
        result.update(metrics.read("batch", reader, wanted))
    return result
