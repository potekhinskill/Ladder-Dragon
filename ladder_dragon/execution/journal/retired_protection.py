# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reconcile canceled OCO siblings without creating exit evidence.
"""A closed parent alone never authorizes retirement of its exchange orders."""

import json

from ladder_dragon.execution.exchange_evidence import (
    checked_list, checked_order, checked_references, exact_nonnegative,
)


def candidates(journal):
    """Bound work before any network access or journal mutation."""
    with journal._session() as con:
        rows = con.execute(
            "SELECT s.* FROM order_intents s JOIN order_intents p "
            "ON p.client_order_id=s.parent_client_order_id AND p.venue=s.venue "
            "AND p.symbol=s.symbol WHERE s.venue=? AND s.side='SELL' "
            "AND s.state='PROTECTED' AND p.side='BUY' AND p.state='CLOSED' "
            "ORDER BY s.client_order_id LIMIT 17", (journal.venue,),
        ).fetchall()
    if len(rows) > 16:
        raise RuntimeError("retired protection reconciliation exceeds capacity")
    return [journal._from_row(row) for row in rows]


def _validate_exchange(protection, payload, legs, stored):
    if protection.order_type != "OCO" or type(protection.exchange_order_list_id) is not int:
        raise RuntimeError("retired protection requires an identified OCO")
    checked_list(payload, client_id=protection.client_order_id,
                 list_id=protection.exchange_order_list_id, symbol=protection.symbol, kind="OCO")
    refs = checked_references(payload, protection.symbol, 2)
    if payload.get("listStatusType") != "ALL_DONE" or len(legs) != 2 or len(stored) != 2:
        raise RuntimeError("retired protection lacks complete terminal evidence")
    expected = {r["order_id"]: (r["client_order_id"], r["leg_type"]) for r in stored}
    if set(expected) != {r["orderId"] for r in refs}:
        raise RuntimeError("retired protection references differ from journal")
    types = set()
    seen = set()
    for ref, leg in zip(refs, legs):
        checked_order(leg, protection.symbol, order_id=ref["orderId"],
                      client_id=ref["clientOrderId"], list_id=protection.exchange_order_list_id)
        if (leg["orderId"] in seen or expected[leg["orderId"]] != (leg["clientOrderId"], leg.get("type"))
                or leg.get("side") != "SELL" or leg.get("status") != "CANCELED"
                or exact_nonnegative(leg.get("executedQty")) != 0
                or exact_nonnegative(leg.get("cummulativeQuoteQty")) != 0
                or exact_nonnegative(leg.get("origQty")) <= 0
                or exact_nonnegative(leg["origQty"]) != exact_nonnegative(protection.quantity)):
            raise RuntimeError("retired protection is not a matched zero-fill cancellation")
        seen.add(leg["orderId"])
        types.add(leg["type"])
    if not (types & {"LIMIT", "LIMIT_MAKER"}) or not (types & {"STOP_LOSS", "STOP_LOSS_LIMIT"}):
        raise RuntimeError("retired protection leg types are invalid")


def retire_canceled(journal, protection, payload, legs):
    """Revalidate exchange and durable evidence together at the final writer."""
    with journal._session(write=True) as con:
        current = journal._from_row(journal._row(con, protection.client_order_id))
        if current is None or current != protection:
            raise RuntimeError("retired protection changed during exchange reads")
        parent = journal._from_row(journal._row(con, current.parent_client_order_id))
        if (parent is None or parent.side != "BUY" or parent.state != "CLOSED"
                or parent.symbol != current.symbol or current.side != "SELL"
                or current.state != "PROTECTED" or (current.metadata or {}).get("exact_lifecycle")):
            raise RuntimeError("retired protection parent or state is invalid")
        closures = con.execute(
            "SELECT x.*,s.state AS protection_state FROM order_lifecycle_closures x "
            "JOIN order_intents s ON s.client_order_id=x.protection_client_order_id "
            "AND s.venue=x.venue AND s.symbol=x.symbol "
            "WHERE x.venue=? AND x.symbol=? AND x.parent_client_order_id=?",
            (journal.venue, current.symbol, parent.client_order_id),
        ).fetchall()
        if (len(closures) != 1 or closures[0]["protection_client_order_id"] == current.client_order_id
                or closures[0]["protection_state"] != "CLOSED"
                or (parent.metadata or {}).get("exact_lifecycle") is not True
                or (parent.metadata or {}).get("exit_order_id") != closures[0]["exit_order_id"]):
            raise RuntimeError("retired protection lacks a separate exact closure")
        stored = con.execute(
            "SELECT order_id,client_order_id,leg_type FROM order_intent_legs "
            "WHERE venue=? AND symbol=? AND protection_client_order_id=?",
            (journal.venue, current.symbol, current.client_order_id),
        ).fetchall()
        _validate_exchange(current, payload, legs, stored)
        metadata = dict(current.metadata or {})
        metadata["zero_fill_cancel_reconciled"] = True
        # Do not modify the parent, fills, quantities, legs, or exact-closure table.
        journal._update_row(con, current.client_order_id, {
            "state": "CANCELED", "last_error": None,
            "metadata_json": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        })


def reconcile_retired_protection(journal, signed_get):
    """Fresh GET-only checks; any ambiguity propagates to the risk gate."""
    for protection in candidates(journal):
        if protection.order_type != "OCO" or type(protection.exchange_order_list_id) is not int:
            raise RuntimeError("retired protection requires an identified OCO")
        payload = signed_get("/api/v3/orderList", {"orderListId": protection.exchange_order_list_id})
        checked_list(payload, client_id=protection.client_order_id,
                     list_id=protection.exchange_order_list_id, symbol=protection.symbol, kind="OCO")
        refs = checked_references(payload, protection.symbol, 2)
        legs = [signed_get("/api/v3/order", {"symbol": protection.symbol, "orderId": ref["orderId"]})
                for ref in refs]
        retire_canceled(journal, protection, payload, legs)
