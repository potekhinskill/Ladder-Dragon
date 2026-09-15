# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind durable net inventory to complete terminal BUY fill evidence.
"""Bounded authoritative evidence inside the existing order journal."""

import json
from decimal import Decimal

from ladder_dragon.execution.buy_settlement import settle_buy, _amount

SETTLEMENT_KEY = "buy_inventory_settlement_v1"
MAXIMUM_SETTLEMENT_BYTES = 2 * 1024 * 1024
ORDER_FIELDS = ("symbol", "orderId", "side", "status", "origQty", "executedQty", "cummulativeQuoteQty")
FILL_FIELDS = ("symbol", "orderId", "id", "isBuyer", "price", "qty", "quoteQty", "commission", "commissionAsset")


def verified_settlement(parent, evidence):
    if not isinstance(evidence, dict) or set(evidence) != {"order", "fills"}:
        raise RuntimeError("BUY settlement evidence is malformed")
    if len(json.dumps(evidence, sort_keys=True).encode()) > MAXIMUM_SETTLEMENT_BYTES:
        raise RuntimeError("BUY settlement evidence exceeds capacity")
    if parent.side != "BUY" or type(parent.exchange_order_id) is not int:
        raise RuntimeError("BUY settlement parent identity is unavailable")
    result = settle_buy(evidence["order"], evidence["fills"],
                        symbol=parent.symbol, order_id=parent.exchange_order_id)
    if (result.gross_quantity != Decimal(parent.executed_qty)
            or result.quote_quantity != Decimal(parent.cumulative_quote_qty)
            or Decimal(evidence["order"]["origQty"]) != Decimal(parent.quantity)):
        raise RuntimeError("BUY settlement differs from durable execution")
    return result


def settlement_evidence(parent, order, fills):
    # Validate before projecting provider fields; no arbitrary response metadata persists.
    verified_settlement(parent, {"order": order, "fills": fills})
    return {"order": {key: order[key] for key in ORDER_FIELDS},
            "fills": [{key: row[key] for key in FILL_FIELDS}
                      for row in sorted(fills, key=lambda row: row["id"])]}


def acquired_quantity(parent):
    """Use verified net evidence when present; never infer an absent fee deduction.

    Legacy records retain their existing gross coverage requirement. They do
    not gain a net-inventory attestation through this compatibility path.
    """
    metadata = getattr(parent, "metadata", None) or {}
    if SETTLEMENT_KEY in metadata:
        return verified_settlement(parent, metadata[SETTLEMENT_KEY]).net_quantity
    try:
        return _amount(parent.executed_qty)
    except ValueError:
        raise RuntimeError("protection quantity evidence is invalid") from None


def record_settlement(journal, client_order_id, order, fills):
    """Commit one immutable evidence set inside the journal transaction."""
    with journal._session(write=True) as con:
        parent = journal._from_row(journal._row(con, client_order_id))
        if parent is None or parent.state == "CLOSED":
            raise RuntimeError("BUY settlement parent is unavailable or closed")
        evidence = settlement_evidence(parent, order, fills)
        metadata = dict(parent.metadata or {})
        if SETTLEMENT_KEY in metadata and metadata[SETTLEMENT_KEY] != evidence:
            raise RuntimeError("BUY settlement evidence is immutable")
        metadata[SETTLEMENT_KEY] = evidence
        row = journal._update_row(con, client_order_id, {
            "metadata_json": json.dumps(metadata, sort_keys=True, separators=(",", ":"))})
    return journal._from_row(row)
