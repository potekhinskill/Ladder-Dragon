# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve order-intent uncertainty during exchange reconciliation.
"""Shared fail-closed boundaries for active order reconciliation."""

from collections.abc import Callable
from typing import TypeVar

import requests

from ladder_dragon.execution.order_recovery import OrderJournal


Result = TypeVar("Result")


def reconcile_active_intent(
    client_order_id: str,
    *,
    journal: OrderJournal,
    lookup: Callable[[], Result],
) -> Result:
    """Mark an active intent unknown when its exchange lookup fails."""
    try:
        return lookup()
    except requests.RequestException as exc:
        journal.mark_unknown(client_order_id, exc)
        raise


def reconcile_active_order(
    journal: OrderJournal,
    client_order_id: str,
    lookup: Callable[[str, str], Result],
    symbol: str,
) -> Result:
    """Reconcile one active order through its symbol and client identity."""
    return reconcile_active_intent(
        client_order_id,
        journal=journal,
        lookup=lambda: lookup(symbol, client_order_id),
    )


def reconcile_active_order_list(
    journal: OrderJournal,
    client_order_id: str,
    lookup: Callable[[str], Result],
) -> Result:
    """Reconcile one active order list through its client identity."""
    return reconcile_active_intent(
        client_order_id,
        journal=journal,
        lookup=lambda: lookup(client_order_id),
    )
