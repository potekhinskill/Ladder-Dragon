# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose MARKET order placement for confirmed emergency paths.

"""MARKET order API."""

from ladder_dragon.execution.orders.runtime import place_market_order

__all__ = ["place_market_order"]
