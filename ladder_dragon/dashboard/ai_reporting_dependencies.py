# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve only declared live AI-reporting dependencies.
"""Live bindings; callable capabilities retain their original scope."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

AI_REPORTING_FIELDS = frozenset(('AI_ERROR_DEGRADED_WINDOW_SEC', 'DASHBOARD_AI_AGGREGATE_CACHE_SEC', '_AI_SUMMARY_CACHE', '_AI_SUMMARY_CACHE_LOCK', '_ai_cache_get', '_ai_cache_put', 'time'))


@dataclass(frozen=True)
class AiReportingState:
    """Resolve current cache, lock, clock, and reporting callbacks."""

    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in AI_REPORTING_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
