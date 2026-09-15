# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify complete order-bound BUY quantities without inferring fee assets.
"""Pure settlement contract; no journal writes or exchange capability."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import re

from ladder_dragon.execution.trade_accounting import TradeExecution, symbol_assets


@dataclass(frozen=True)
class BuySettlement:
    symbol: str
    order_id: int
    gross_quantity: Decimal
    net_quantity: Decimal
    quote_quantity: Decimal
    trade_ids: tuple[int, ...]


def require_full_inventory_coverage(required: Decimal, normalized: Decimal) -> None:
    """Neither rounding nor free balance can prove an inventory write-off."""
    if (not isinstance(required, Decimal) or not isinstance(normalized, Decimal)
            or not required.is_finite() or not normalized.is_finite()
            or required <= 0 or normalized != required):
        raise RuntimeError("net BUY residual cannot be fully protected after quantity normalization")


def _amount(value, *, positive=False):
    if (not isinstance(value, str) or not value or len(value) > 128
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is None):
        raise ValueError("settlement amount must be an exact decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("settlement amount is invalid") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("settlement amount is out of range")
    return result


def settle_buy(order: dict, fills: list[dict], *, symbol: str, order_id: int) -> BuySettlement:
    """Require every gross fill before deriving net inventory through its owner.

    Quote and third-asset fees do not change acquired base quantity. This
    contract does not value third-asset fees or attest profit or exact closure.
    """
    # Two bounded 128-character operands and at most 10,000 rows fit exactly.
    # Do not let ambient Decimal precision erase an inventory fee.
    with localcontext() as arithmetic:
        arithmetic.prec = 512
        return _settle_buy(order, fills, symbol=symbol, order_id=order_id)


def _settle_buy(order, fills, *, symbol, order_id):
    if (not isinstance(order, dict) or type(order_id) is not int or order_id < 0
            or order.get("symbol") != symbol or order.get("side") != "BUY"
            or type(order.get("orderId")) is not int or order["orderId"] != order_id
            or order.get("status") not in {"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}):
        raise ValueError("settlement requires an identified terminal BUY")
    original = _amount(order.get("origQty"), positive=True)
    expected = _amount(order.get("executedQty"), positive=True)
    expected_quote = _amount(order.get("cummulativeQuoteQty"), positive=True)
    if expected > original or (order["status"] == "FILLED" and expected != original):
        raise ValueError("settlement terminal quantity is inconsistent")
    if not isinstance(fills, list) or not 1 <= len(fills) <= 10000:
        raise ValueError("settlement fills are missing or exceed capacity")
    base, quote_asset = symbol_assets(symbol)
    gross = net = quote = Decimal("0")
    ids = set()
    for fill in fills:
        if (not isinstance(fill, dict) or fill.get("symbol") != symbol
                or type(fill.get("orderId")) is not int or fill["orderId"] != order_id
                or fill.get("isBuyer") is not True or type(fill.get("id")) is not int
                or fill["id"] < 0 or fill["id"] in ids):
            raise ValueError("settlement fill identity is invalid or duplicated")
        ids.add(fill["id"])
        qty = _amount(fill.get("qty"), positive=True)
        price = _amount(fill.get("price"), positive=True)
        notional = _amount(fill.get("quoteQty"), positive=True)
        commission = _amount(fill.get("commission"))
        asset = fill.get("commissionAsset")
        if (not isinstance(asset, str) or not asset or len(asset) > 32
                or not asset.isalnum() or asset != asset.upper()
                or asset not in {base, quote_asset, "BNB"}):
            raise ValueError("settlement commission asset is unavailable")
        if notional != qty * price:
            raise ValueError("settlement fill quote quantity differs")
        execution = TradeExecution.create(
            symbol=symbol, side="BUY", price=price, gross_qty=qty,
            commission_asset=asset, commission_amount=commission,
        )
        gross += execution.gross_qty
        net += execution.net_qty
        quote += notional
    if gross != expected or quote != expected_quote:
        raise ValueError("settlement fills do not cover the terminal BUY")
    if not Decimal("0") < net <= gross:
        raise ValueError("settlement net inventory is invalid")
    return BuySettlement(symbol, order_id, gross, net, quote, tuple(sorted(ids)))
