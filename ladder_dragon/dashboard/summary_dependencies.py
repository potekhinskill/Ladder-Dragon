# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve only declared live summary-route dependencies.
"""Live bindings; callable capabilities retain their original scope."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SUMMARY_FIELDS = frozenset(('_EQUITY_SUMMARY_CACHE', '_database_unavailable_response', '_fee_pct_default', '_fifo_realized_pnl', '_load_trades', '_open_db', 'equity_pnl_usdt', 'time'))


@dataclass(frozen=True)
class SummaryRouteState:
    """Resolve current accounting readers and the equity cache."""

    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in SUMMARY_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
