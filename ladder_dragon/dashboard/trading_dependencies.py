# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve only declared live trading-route dependencies.
"""A read-only interface to current dependencies, not a security sandbox."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

TRADING_FIELDS = frozenset((
    '_BALANCE_CACHE',
    '_BALANCE_CACHE_LOCK',
    '_DATA_SOURCE_ERRORS',
    '_OPEN_ORDERS_CACHE',
    '_OPEN_ORDERS_CACHE_LOCK',
    '_stale_binance_snapshot',
    'account_balances_snapshot',
    'account_open_orders_snapshot',
    'market_analysis_snapshot',
    'trading_overview_snapshot',
))


@dataclass(frozen=True)
class TradingRouteState:
    """Keep current cache, lock, exception, and reader bindings across requests."""

    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in TRADING_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
