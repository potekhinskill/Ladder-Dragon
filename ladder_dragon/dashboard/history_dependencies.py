# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve only declared live history-route dependencies.
"""A read-only interface to current dependencies, not a security sandbox."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

HISTORY_FIELDS = frozenset(('APP_TZ', '_database_unavailable_response', '_fee_pct_default', '_open_db', 'time'))


@dataclass(frozen=True)
class HistoryRouteState:
    """Resolve current database, clock, timezone, and fee-reader bindings."""

    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in HISTORY_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
