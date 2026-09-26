# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve only declared live control-route dependencies.
"""Live bindings; callable capabilities retain their original scope."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

CONTROL_FIELDS = frozenset(('AI_CONTROL_FILE', 'AI_MODE', '_load_ai_runtime_status', 'read_ai_control', 'write_ai_control'))


@dataclass(frozen=True)
class ControlRouteState:
    """Resolve current advisory configuration, canonical readers, and writer."""

    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in CONTROL_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
