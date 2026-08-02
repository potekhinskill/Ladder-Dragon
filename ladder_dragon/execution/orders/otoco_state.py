# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: persist the strongest verified OTOCO journal state.

"""OTOCO journal-state finalization."""

from typing import Any

from ladder_dragon.execution.order_recovery import OrderJournal


def record_verified_otoco(
    journal: OrderJournal,
    *,
    working_client_id: str,
    list_client_id: str,
    order_list: dict[str, Any],
    working: dict[str, Any],
    pending: list[dict[str, Any]],
) -> None:
    """Record one verified OTOCO list with the strongest proven state."""
    journal.record_exchange_order(working_client_id, working)
    journal.record_order_list(list_client_id, order_list)
    protection_active = (
        str(working.get("status") or "").upper() == "FILLED"
        and all(
            str(order.get("status") or "").upper()
            in {"NEW", "PARTIALLY_FILLED"}
            for order in pending
        )
    )
    if protection_active:
        order_list_id = order_list.get("orderListId")
        journal.mark_verified_protected(
            parent_client_order_id=working_client_id,
            protection_client_order_id=list_client_id,
            legs=pending,
            order_list_id=int(order_list_id) if order_list_id is not None else None,
        )
    else:
        journal.record_verified_protection_legs(list_client_id, pending)
