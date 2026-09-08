# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: share exact response identity and account evidence at every consumer.
"""Never replace malformed provider state with an empty financial observation."""

from decimal import Decimal, InvalidOperation
import unicodedata


class MarketIdentityError(ValueError):
    """Do not replace identity corruption with an alternate endpoint."""


def exact_nonnegative(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 128:
        raise ValueError("invalid exact exchange number")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError("invalid exact exchange number") from None
    if not value.is_finite() or value < 0:
        raise ValueError("invalid exact exchange number")
    return value


def checked_balances(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("balances"), list):
        raise ValueError("invalid account balance collection")
    result = {}
    for row in payload["balances"]:
        if not isinstance(row, dict):
            raise ValueError("invalid account balance row")
        asset = row.get("asset")
        # Asset names are opaque UTF-8 strings, not ASCII trading config tokens.
        if (not isinstance(asset, str) or not asset or len(asset) > 128
                or any(char.isspace() or unicodedata.category(char).startswith("C") for char in asset)
                or asset in result):
            raise ValueError("invalid or duplicate account asset")
        result[asset] = {key: exact_nonnegative(row.get(key)) for key in ("free", "locked")}
    return result


def checked_market(payload, symbol):
    if not isinstance(payload, dict) or payload.get("symbol") != symbol:
        raise MarketIdentityError("ticker symbol differs from requested market")
    return payload


def checked_order(payload, symbol, *, order_id=None, client_id=None, list_id=None):
    if (not isinstance(payload, dict) or payload.get("symbol") != symbol
            or type(payload.get("orderId")) is not int or payload["orderId"] < 0
            or not isinstance(payload.get("clientOrderId"), str) or not payload["clientOrderId"]
            or (order_id is not None and payload["orderId"] != order_id)
            or (client_id is not None and payload["clientOrderId"] != client_id)
            or (list_id is not None and (type(payload.get("orderListId")) is not int
                                       or payload["orderListId"] != list_id))):
        raise RuntimeError("exchange order identity differs from requested evidence")
    return payload


def checked_list(payload, *, client_id=None, list_id=None, symbol=None, kind=None):
    # Binance reports both two-order OTO and three-order OTOCO as OTO.
    expected_kind = "OTO" if kind == "OTOCO" else kind
    if (not isinstance(payload, dict)
            or type(payload.get("orderListId")) is not int or payload["orderListId"] < 0
            or not isinstance(payload.get("listClientOrderId"), str) or not payload["listClientOrderId"]
            or (client_id is not None and payload["listClientOrderId"] != client_id)
            or (list_id is not None and payload["orderListId"] != list_id)
            or (symbol is not None and payload.get("symbol") != symbol)
            or (kind is not None and payload.get("contingencyType") != expected_kind)):
        raise RuntimeError("exchange order-list identity differs from durable evidence")
    return payload


def checked_references(payload, symbol, count):
    refs = payload.get("orders")
    if not isinstance(refs, list) or len(refs) != count:
        raise RuntimeError("exchange order-list references are incomplete")
    ids, clients = set(), set()
    for ref in refs:
        checked_order(ref, symbol)
        if ref["orderId"] in ids or ref["clientOrderId"] in clients:
            raise RuntimeError("exchange order-list references are duplicated")
        ids.add(ref["orderId"])
        clients.add(ref["clientOrderId"])
    return refs
