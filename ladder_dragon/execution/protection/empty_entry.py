# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: record terminal unfilled BUY orders without creating protection.
"""Record terminal unfilled entries without position protection."""

import sqlite3


def record_empty_entry(symbol, order_id, order, status, dependencies, terminal_unfilled_order_ids):
    try:
        journal = dependencies.journal()
        intent = (
            journal.get_by_exchange_order_id(order_id)
            if journal is not None
            else None
        )
        if journal is not None and intent is not None:
            journal.record_exchange_order(intent.client_order_id, order)
    except (sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
        dependencies.logger(
            f"[PROTECTION-JOURNAL] {symbol} order={order_id}: {exc}"
        )
    if terminal_unfilled_order_ids is not None:
        terminal_unfilled_order_ids.add(order_id)
    dependencies.logger(
        f"[PROTECTION] {symbol} BUY order={order_id} "
        f"state={status} executed=0; OCO not needed"
    )
