# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: detect post-import replacement of supervisor execution authority.
"""Fail closed when the supervisor execution-authority binding changes."""

from __future__ import annotations

from collections.abc import Callable

from ladder_dragon.strategy.prediction.champion_registry import (
    verify_active_champion_lifecycle as _CANONICAL_SUPERVISOR_AUTHORITY,
)


class SupervisorAuthorityBindingError(RuntimeError):
    """Report a changed supervisor authority without callable details."""


def require_supervisor_authority_binding(observed: Callable[..., object]) -> None:
    """Require the import-time supervisor authority object."""
    if observed is not _CANONICAL_SUPERVISOR_AUTHORITY:
        raise SupervisorAuthorityBindingError(
            "supervisor execution authority runtime binding changed"
        )


__all__ = [
    "SupervisorAuthorityBindingError",
    "require_supervisor_authority_binding",
]
