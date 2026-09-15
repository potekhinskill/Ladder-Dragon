# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind causal commission references to durable fills and pinned record bytes.
"""Read-only qualification adapter; external source authentication remains required."""

from dataclasses import dataclass
import hashlib
import json
import re

from ladder_dragon.execution.exchange_evidence import checked_trade
from ladder_dragon.execution.journal.buy_inventory import (
    MAXIMUM_SETTLEMENT_BYTES, SETTLEMENT_KEY, settlement_evidence, verified_settlement,
)
from ladder_dragon.strategy.prediction.causal_commission import CausalCommission, value_bnb_commission


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("commission record has duplicate fields")
        result[key] = value
    return result


def _pinned_json(raw, expected_sha256, maximum_bytes):
    if (type(raw) is not bytes or not 0 < len(raw) <= maximum_bytes
            or not isinstance(expected_sha256, str)
            or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        raise ValueError("commission record size or pinned hash differs")
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        # Provider bodies and parser excerpts must not enter diagnostics.
        raise ValueError("commission record JSON is invalid") from None


@dataclass(frozen=True)
class BoundCommission:
    symbol: str
    order_id: int
    trade_id: int
    fill_time_ms: int
    fill_source_sha256: str
    valuation: CausalCommission


def settled_bnb_fill(*, parent, trade_id, fills_bytes, fills_sha256):
    """Share complete durable fill binding across REST and WebSocket evidence."""
    if type(trade_id) is not int or trade_id < 0:
        raise ValueError("commission trade identity is invalid")
    stored = (getattr(parent, "metadata", None) or {}).get(SETTLEMENT_KEY)
    verified_settlement(parent, stored)
    fills = _pinned_json(fills_bytes, fills_sha256, MAXIMUM_SETTLEMENT_BYTES)
    if not isinstance(fills, list) or not 1 <= len(fills) <= 10000:
        raise ValueError("commission fill collection is invalid")
    for fill in fills:
        checked_trade(fill, parent.symbol)
    if settlement_evidence(parent, stored["order"], fills) != stored:
        raise ValueError("commission fills differ from durable settlement")
    selected = next((fill for fill in fills if fill["id"] == trade_id), None)
    if selected is None or selected["commissionAsset"] != "BNB":
        raise ValueError("settled BNB commission fill is unavailable")
    return selected


def value_settled_bnb_fill(*, parent, trade_id, fills_bytes, fills_sha256,
                          price_event_bytes, price_event_sha256, max_age_ms):
    """Bind WebSocket prices to complete fills; source authentication stays separate."""
    selected = settled_bnb_fill(parent=parent, trade_id=trade_id,
                                fills_bytes=fills_bytes, fills_sha256=fills_sha256)
    price = _pinned_json(price_event_bytes, price_event_sha256, 16384)
    if (not isinstance(price, dict) or price.get("e") != "aggTrade"
            or price.get("_source") != "binance-public-websocket"
            or any(type(price.get(key)) is not int or price[key] < 0 for key in ("a", "T", "E", "_received_at_ms"))
            or not 0 < price["T"] <= price["E"] <= price["_received_at_ms"]):
        raise ValueError("commission price event identity or time is invalid")
    valuation = value_bnb_commission(
        symbol=parent.symbol, commission_amount=selected["commission"],
        fill_time_ms=selected["time"], max_age_ms=max_age_ms,
        price_evidence=dict(symbol=price.get("s"), price=price.get("p"),
                            market_time_ms=price["T"], available_at_ms=price["_received_at_ms"],
                            source_sha256=price_event_sha256),
    )
    return BoundCommission(parent.symbol, parent.exchange_order_id, trade_id,
                           selected["time"], fills_sha256, valuation)
