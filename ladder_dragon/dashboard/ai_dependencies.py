# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve only declared live AI-status dependencies.
"""Live bindings; callable capabilities retain their original scope."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

AI_FIELDS = frozenset(('AI_DAILY_COST_LIMIT_USD', 'AI_DAILY_TOKEN_LIMIT', 'AI_DECISIONS_DB', 'AI_ERROR_DEGRADED_MIN', 'AI_MAX_REQUESTS_PER_DAY', 'AI_MODE', 'AI_USAGE_LOG', 'DASHBOARD_FOLLOW_BOT_PATHS', '_ai_calibration', '_ai_database_aggregates', '_ai_usage_today', '_load_ai_runtime_status', '_runtime_data_path', 'runtime_degraded_reason', 'time'))


@dataclass(frozen=True)
class AiRouteState:
    """Resolve current declared AI-status presentation dependencies."""

    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in AI_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
