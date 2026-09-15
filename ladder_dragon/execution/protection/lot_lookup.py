# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: find protection lots through the worker's current resources.
"""Resolve lot identity through current worker resources."""

import sqlite3


def lot_id_for_fill(runtime, symbol, fill_price, order_id=None):
    if runtime["STATS_CON"] is None:
        return None
    try:
        if order_id is not None:
            exact = runtime["lot_for_order"](runtime["STATS_CON"], symbol, order_id)
            if exact is not None:
                return exact.lot_id
        lots = runtime["oldest_lots"](runtime["STATS_CON"], symbol)
        return lots[0].lot_id if lots else None
    except sqlite3.Error:
        return None
