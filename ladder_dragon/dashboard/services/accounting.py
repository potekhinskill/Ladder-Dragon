# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: provide display-only accounting helpers for dashboard read models.

"""Dashboard accounting helpers; execution decisions never import this module."""

from ladder_dragon.execution.trade_accounting import base_asset


def base_asset_of(symbol: str) -> str:
    """Infer the base asset for a display-only Binance symbol."""
    normalized = str(symbol).upper()
    try:
        return base_asset(normalized)
    except ValueError:
        # Display-only legacy rows retain their original label.
        return normalized
