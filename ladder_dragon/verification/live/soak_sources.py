# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a Testnet soak boundary without changing monitoring behavior.
"""Testnet soak_sources implementation."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from ladder_dragon.execution.exchange_math import decimal
from ladder_dragon.verification.live.testnet_smoke import balance_amount
from ladder_dragon.verification.live.soak_policy import oco_protection_coverage


def _inventory_qty(db_path: str, symbol: str) -> Decimal:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as con:
        row = con.execute(
            "SELECT qty_text FROM inventory_exact WHERE symbol=?", (symbol,)
        ).fetchone()
    return decimal(row[0]) if row else Decimal("0")


def _read_sources(client, symbol, base_asset, db_path, rules):
    account = client.signed("GET", "/api/v3/account")
    orders = client.signed(
        "GET", "/api/v3/openOrders", {"symbol": symbol}
    )
    price = decimal(
        client.public_get(
            "/api/v3/ticker/price", {"symbol": symbol}
        )["price"]
    )
    account_qty = balance_amount(account, base_asset) + balance_amount(
        account, base_asset, "locked"
    )
    ledger_qty = _inventory_qty(db_path, symbol)
    open_buys = [
        row for row in orders if str(row.get("side")).upper() == "BUY"
    ]
    open_sells = [
        row for row in orders if str(row.get("side")).upper() == "SELL"
    ]
    protected_legs, protected_qty, protection_complete = (
        oco_protection_coverage(
            open_sells,
            quantity_tolerance=rules["step"],
        )
    )
    open_buy_exposure = sum(
        decimal(row.get("price"))
        * (decimal(row.get("origQty")) - decimal(row.get("executedQty")))
        for row in open_buys
    )
    holdings = account_qty * price
    return (account_qty, ledger_qty, price, open_buys, open_sells,
            protected_legs, protected_qty, protection_complete, open_buy_exposure, holdings)
