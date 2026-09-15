# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: share exact terminal-order completeness across read-only consumers.
"""Shared read-only terminal order and complete fill-set validation."""
from decimal import Decimal, localcontext
import re

from ladder_dragon.execution.exchange_evidence import checked_trade, valid_exchange_name


def terminal_order(order, symbol, order_id):
    if (not valid_exchange_name(symbol) or type(order_id) is not int or order_id < 0
            or not isinstance(order, dict) or order.get('symbol') != symbol
            or type(order.get('orderId')) is not int or order['orderId'] != order_id
            or order.get('side') not in {'BUY', 'SELL'}
            or order.get('status') not in {'FILLED', 'CANCELED', 'EXPIRED', 'EXPIRED_IN_MATCH'}):
        raise ValueError('PROBE_TERMINAL_ORDER_INVALID')
    values = []
    for key in ('origQty', 'executedQty', 'cummulativeQuoteQty'):
        values.append(amount(order.get(key)))
    original, executed, quote = values
    if not 0 < executed <= original or (order['status'] == 'FILLED' and executed != original):
        raise ValueError('PROBE_ORDER_QUANTITY_INVALID')
    return executed, quote


def amount(value):
    if not isinstance(value, str) or len(value) > 128 or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value) is None:
        raise ValueError('PROBE_EXACT_AMOUNT_INVALID')
    return Decimal(value)


def complete_fills(order, fills, symbol, order_id):
    executed, quote = terminal_order(order, symbol, order_id)
    if not isinstance(fills, list) or not 1 <= len(fills) <= 1000:
        raise ValueError('PROBE_ORDER_FILLS_INVALID')
    indexed = {}
    # Bounded exact operands and complete totals must not depend on ambient precision.
    with localcontext() as context:
        context.prec = 512
        quantity_sum = quote_sum = Decimal('0')
        for fill in fills:
            checked_trade(fill, symbol)
            if (fill['orderId'] != order_id or fill['isBuyer'] != (order['side'] == 'BUY')
                    or fill['id'] in indexed):
                raise ValueError('PROBE_ORDER_FILL_IDENTITY_INVALID')
            price, qty, paid = (amount(fill.get(k)) for k in ('price', 'qty', 'quoteQty'))
            if price * qty != paid:
                raise ValueError('PROBE_FILL_QUOTE_INVALID')
            quantity_sum += qty
            quote_sum += paid
            indexed[fill['id']] = fill
        if quantity_sum != executed or quote_sum != quote:
            raise ValueError('PROBE_ORDER_FILLS_INCOMPLETE')
    return indexed
