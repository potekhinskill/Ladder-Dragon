# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: detect post-import replacement of worker execution authority.
"""Fail closed when the worker execution-authority binding changes."""

from __future__ import annotations

from collections.abc import Callable

from ladder_dragon.execution.worker.champion_preflight import (
    require_live_champion as _CANONICAL_WORKER_AUTHORITY,
)


class WorkerAuthorityBindingError(RuntimeError):
    """Report a changed worker authority without callable details."""


def require_worker_authority_binding(observed: Callable[..., object]) -> None:
    """Require the import-time worker authority object."""
    if observed is not _CANONICAL_WORKER_AUTHORITY:
        raise WorkerAuthorityBindingError(
            "worker execution authority runtime binding changed"
        )


__all__ = ["WorkerAuthorityBindingError", "require_worker_authority_binding"]
