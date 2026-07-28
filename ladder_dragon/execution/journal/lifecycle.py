# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define atomic lifecycle-transition contracts.

"""Lifecycle contracts kept separate from journal persistence details."""

from typing import Protocol


class LifecycleWriter(Protocol):
    """Atomic lifecycle operations required by protection services."""

    def mark_exact_lifecycle_closed(
        self,
        parent_client_order_id: str,
        protection_client_order_id: str,
        *,
        exit_reason: str,
        exit_order_id: int,
    ) -> None:
        """Close parent and protection in one database transaction."""
