# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the existing dashboard access boundary.

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SECURITY_FIELDS = frozenset(('DASHBOARD_CSRF_TOKEN',))
ACCESS_FIELDS = frozenset(('DASHBOARD_AUTH_TOKEN', 'DASHBOARD_CSRF_TOKEN', 'DASHBOARD_PROXY_AUTH_SECRET', 'DASHBOARD_RATE_LIMIT_PER_MIN', 'DASHBOARD_TRUST_PROXY_AUTH', '_RATE_BUCKETS', '_RATE_LOCK', '_RATE_PRUNE_STATE', 'time'))


@dataclass(frozen=True)
class SecurityRouteState:
    """Resolve current declared bindings without exposing values in repr."""
    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in SECURITY_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None


@dataclass(frozen=True)
class AccessState:
    """Resolve current declared bindings without exposing values in repr."""
    _namespace: Mapping[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name not in ACCESS_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
