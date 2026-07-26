# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the inventory lots component of the execution layer.
"""Ladder Dragon inventory lots support."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from ladder_dragon.execution.trade_accounting import TradeExecution


@dataclass(frozen=True)
class InventoryLot:
    """Represent InventoryLot."""
    lot_id: int
    symbol: str
    qty: Decimal
    price: Decimal
    opened_at: int
    ladder_level: str


@dataclass(frozen=True)
class CostBasisCoverage:
    """Exact quantity coverage of account inventory by priced, sourced lots."""

    symbol: str
    account_qty: Decimal
    covered_qty: Decimal
    average_price: Decimal | None
    uncovered_qty: Decimal
    tolerance_qty: Decimal
    covered: bool
    reason: str


def ensure_schema(connection: sqlite3.Connection) -> None:
    # Store Decimal values as text so SQLite cannot round quantity or price.
    connection.execute("""CREATE TABLE IF NOT EXISTS inventory_lots(
        lot_id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
        qty TEXT NOT NULL, price TEXT NOT NULL, opened_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL, ladder_level TEXT NOT NULL DEFAULT '',
        source_order_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'OPEN'
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS inventory_lots_fifo ON inventory_lots(symbol,status,opened_at)")
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(inventory_lots)")
    }
    if "source_trade_id" not in columns:
        connection.execute(
            "ALTER TABLE inventory_lots ADD COLUMN source_trade_id TEXT NOT NULL DEFAULT ''"
        )
    if "import_batch_id" not in columns:
        connection.execute(
            "ALTER TABLE inventory_lots ADD COLUMN import_batch_id TEXT NOT NULL DEFAULT ''"
        )
    # SELL fills need the same durable exchange-trade idempotency as BUY lots.
    # One Binance trade ID may consume multiple FIFO lots, so this header stores
    # the exact normalized fill once while inventory_lots retains the allocation.
    connection.execute(
        """CREATE TABLE IF NOT EXISTS inventory_lot_consumptions(
            symbol TEXT NOT NULL, source_trade_id TEXT NOT NULL,
            source_order_id TEXT NOT NULL DEFAULT '', qty TEXT NOT NULL,
            price TEXT NOT NULL, executed_at INTEGER NOT NULL,
            recorded_at INTEGER NOT NULL,
            PRIMARY KEY(symbol,source_trade_id)
        )"""
    )


def add_lot(connection: sqlite3.Connection, *, symbol: str, qty: Decimal, price: Decimal,
            ladder_level: str = "", opened_at: int | None = None,
            source_order_id: str = "", source_trade_id: str | int = "",
            import_batch_id: str = "") -> int:
    ensure_schema(connection)
    normalized_symbol = symbol.upper()
    normalized_trade_id = str(source_trade_id).strip()
    normalized_order_id = str(source_order_id).strip()
    normalized_qty = Decimal(qty)
    normalized_price = Decimal(price)
    if (
        not normalized_qty.is_finite()
        or normalized_qty <= 0
        or not normalized_price.is_finite()
        or normalized_price <= 0
    ):
        raise ValueError("inventory lot quantity and price must be positive")
    if normalized_trade_id:
        existing = connection.execute(
            "SELECT lot_id,qty,price,source_order_id,import_batch_id "
            "FROM inventory_lots "
            "WHERE symbol=? AND source_trade_id=? ORDER BY lot_id LIMIT 1",
            (normalized_symbol, normalized_trade_id),
        ).fetchone()
        if existing is not None:
            if (
                Decimal(str(existing[1])) != normalized_qty
                or Decimal(str(existing[2])) != normalized_price
                or str(existing[3] or "").strip() != normalized_order_id
                or str(existing[4] or "").strip() != import_batch_id.strip()
            ):
                raise ValueError(
                    "inventory BUY source trade payload mismatch"
                )
            return int(existing[0])
    # Historical imports may provide the original BUY timestamp.
    now = int(opened_at or time.time())
    cur = connection.execute(
        "INSERT INTO inventory_lots("
        "symbol,qty,price,opened_at,updated_at,ladder_level,source_order_id,"
        "source_trade_id,import_batch_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            normalized_symbol, str(normalized_qty), str(normalized_price),
            now, now, ladder_level, normalized_order_id,
            normalized_trade_id, import_batch_id,
        ),
    )
    return int(cur.lastrowid)


def oldest_lots(connection: sqlite3.Connection, symbol: str) -> list[InventoryLot]:
    # Sorting by opened_at guarantees FIFO and enables time-stop handling.
    ensure_schema(connection)
    rows = connection.execute(
        "SELECT lot_id,symbol,qty,price,opened_at,ladder_level FROM inventory_lots WHERE symbol=? AND status='OPEN' ORDER BY opened_at,lot_id",
        (symbol.upper(),),
    ).fetchall()
    lots: list[InventoryLot] = []
    for row in rows:
        quantity = Decimal(str(row[2]))
        # Zero, negative and non-finite OPEN rows are damaged state, not FIFO
        # allocations. Ignoring them prevents zero-quantity consumption records;
        # the final sufficiency check still fails closed if valid lots are short.
        if not quantity.is_finite() or quantity <= 0:
            continue
        lots.append(
            InventoryLot(
                int(row[0]),
                str(row[1]),
                quantity,
                Decimal(str(row[3])),
                int(row[4]),
                str(row[5]),
            )
        )
    return lots


def lot_for_order(connection: sqlite3.Connection, symbol: str, order_id: str | int) -> InventoryLot | None:
    """Handle lot for order."""
    ensure_schema(connection)
    row = connection.execute(
        "SELECT lot_id,symbol,qty,price,opened_at,ladder_level FROM inventory_lots "
        "WHERE symbol=? AND source_order_id=? AND status='OPEN' ORDER BY opened_at,lot_id LIMIT 1",
        (symbol.upper(), str(order_id)),
    ).fetchone()
    return InventoryLot(int(row[0]), str(row[1]), Decimal(row[2]), Decimal(row[3]), int(row[4]), str(row[5])) if row else None


def cost_basis_coverage(
    connection: sqlite3.Connection,
    symbol: str,
    account_qty: Decimal,
    *,
    tolerance_qty: Decimal = Decimal("0"),
) -> CostBasisCoverage:
    """Prove that account quantity is covered by priced, attributable lots.

    Rows without a positive price or source identifier are deliberately not
    counted. This prevents an arbitrary quantity-only import from authorizing
    legacy holdings management.
    """
    ensure_schema(connection)
    account = Decimal(account_qty)
    tolerance = max(Decimal("0"), Decimal(tolerance_qty))
    if not account.is_finite() or account < 0:
        raise ValueError("account quantity must be finite and non-negative")
    rows = connection.execute(
        "SELECT qty,price,source_order_id,source_trade_id FROM inventory_lots "
        "WHERE symbol=? AND status='OPEN' ORDER BY opened_at,lot_id",
        (symbol.upper(),),
    ).fetchall()
    covered_qty = Decimal("0")
    covered_cost = Decimal("0")
    incomplete_rows = 0
    for qty_text, price_text, source_order_id, source_trade_id in rows:
        qty = Decimal(str(qty_text))
        price = Decimal(str(price_text))
        if qty <= 0:
            continue
        if price <= 0 or not (
            str(source_order_id or "").strip()
            or str(source_trade_id or "").strip()
        ):
            incomplete_rows += 1
            continue
        covered_qty += qty
        covered_cost += qty * price
    delta = account - covered_qty
    covered = incomplete_rows == 0 and abs(delta) <= tolerance
    if incomplete_rows:
        reason = "inventory lots contain missing price or provenance"
    elif delta > tolerance:
        reason = "account inventory contains uncovered legacy quantity"
    elif delta < -tolerance:
        reason = "inventory lots exceed the Binance account quantity"
    else:
        reason = "covered"
    return CostBasisCoverage(
        symbol=symbol.upper(),
        account_qty=account,
        covered_qty=covered_qty,
        average_price=(covered_cost / covered_qty if covered_qty > 0 else None),
        uncovered_qty=max(Decimal("0"), delta),
        tolerance_qty=tolerance,
        covered=covered,
        reason=reason,
    )


def consume_fifo(connection: sqlite3.Connection, symbol: str, qty: Decimal) -> list[InventoryLot]:
    """Plan and atomically consume positive FIFO lots."""
    requested = Decimal(qty)
    if not requested.is_finite() or requested <= 0:
        raise ValueError("FIFO consumption quantity must be positive")

    # First pass is read-only. Never mutate a prefix of inventory before proving
    # that the complete SELL quantity is covered.
    consumed: list[InventoryLot] = []
    remaining = requested
    for lot in oldest_lots(connection, symbol):
        if remaining <= 0:
            break
        used = min(remaining, lot.qty)
        consumed.append(
            InventoryLot(
                lot.lot_id,
                lot.symbol,
                used,
                lot.price,
                lot.opened_at,
                lot.ladder_level,
            )
        )
        remaining -= used
    if remaining > 0:
        raise ValueError("SELL exceeds FIFO inventory lots")

    # Second pass applies the complete plan under a savepoint. This remains
    # atomic even on the autocommit statistics connection or a mid-loop SQLite
    # failure; callers also rollback before continuing.
    connection.execute("SAVEPOINT inventory_fifo_consume")
    try:
        updated_at = int(time.time())
        current_lots = oldest_lots(connection, symbol)
        planned_ids = [allocation.lot_id for allocation in consumed]
        if [lot.lot_id for lot in current_lots[:len(planned_ids)]] != planned_ids:
            raise RuntimeError("FIFO inventory order changed during consumption")
        lots_by_id = {lot.lot_id: lot for lot in current_lots}
        for allocation in consumed:
            current = lots_by_id.get(allocation.lot_id)
            if current is None or current.qty < allocation.qty:
                raise RuntimeError("FIFO inventory changed during consumption")
            left = current.qty - allocation.qty
            cursor = connection.execute(
                "UPDATE inventory_lots SET qty=?,updated_at=?,status=? "
                "WHERE lot_id=? AND status='OPEN' AND qty=?",
                (
                    str(left),
                    updated_at,
                    "OPEN" if left > 0 else "CLOSED",
                    allocation.lot_id,
                    str(current.qty),
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "FIFO inventory changed during consumption"
                )
        connection.execute("RELEASE SAVEPOINT inventory_fifo_consume")
    except (
        ArithmeticError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ):
        connection.execute("ROLLBACK TO SAVEPOINT inventory_fifo_consume")
        connection.execute("RELEASE SAVEPOINT inventory_fifo_consume")
        raise
    return consumed


def sync_exchange_fill(
    connection: sqlite3.Connection, fill: Mapping[str, Any]
) -> int | list[InventoryLot]:
    """Apply one exact Binance fill to age-aware FIFO lots idempotently."""
    symbol = str(fill["symbol"]).upper()
    execution = TradeExecution.create(
        symbol=symbol,
        side=str(fill["side"]),
        price=fill["price"],
        gross_qty=fill["qty"],
        commission_asset=str(fill.get("commission_asset") or ""),
        commission_amount=fill.get("commission_amount") or "0",
        commission_quote=fill.get("fee_quote"),
        commission_value_status=str(
            fill.get("fee_status")
            or (
                "exact"
                if fill.get("fee_quote") is not None
                else "unpriced"
            )
        ),
    )
    source_trade_id = str(fill["trade_id"]).strip()
    if not source_trade_id:
        raise ValueError("exchange fill trade_id is required")
    source_order_id = str(fill.get("order_id") or "").strip()
    if execution.side == "BUY":
        unit_cost = execution.buy_cost_quote() / execution.net_qty
        return add_lot(
            connection,
            symbol=symbol,
            qty=execution.net_qty,
            price=unit_cost,
            source_order_id=source_order_id,
            source_trade_id=source_trade_id,
            opened_at=int(int(fill["ts"]) / 1000),
        )

    ensure_schema(connection)
    connection.execute("SAVEPOINT inventory_sell_fill")
    try:
        existing = connection.execute(
            "SELECT source_order_id,qty,price FROM "
            "inventory_lot_consumptions "
            "WHERE symbol=? AND source_trade_id=?",
            (symbol, source_trade_id),
        ).fetchone()
        if existing is not None:
            recorded_order_id = str(existing[0] or "").strip()
            if (
                (recorded_order_id and recorded_order_id != source_order_id)
                or Decimal(str(existing[1])) != execution.net_qty
                or Decimal(str(existing[2])) != execution.price
            ):
                raise ValueError(
                    "inventory SELL source trade payload mismatch"
                )
            if not recorded_order_id and source_order_id:
                connection.execute(
                    "UPDATE inventory_lot_consumptions "
                    "SET source_order_id=? "
                    "WHERE symbol=? AND source_trade_id=?",
                    (source_order_id, symbol, source_trade_id),
                )
            connection.execute("RELEASE SAVEPOINT inventory_sell_fill")
            return []

        consumed = consume_fifo(connection, symbol, execution.net_qty)
        connection.execute(
            "INSERT INTO inventory_lot_consumptions("
            "symbol,source_trade_id,source_order_id,qty,price,executed_at,"
            "recorded_at) VALUES(?,?,?,?,?,?,?)",
            (
                symbol,
                source_trade_id,
                source_order_id,
                str(execution.net_qty),
                str(execution.price),
                int(fill["ts"]),
                int(time.time()),
            ),
        )
        connection.execute("RELEASE SAVEPOINT inventory_sell_fill")
        return consumed
    except (ArithmeticError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        connection.execute("ROLLBACK TO SAVEPOINT inventory_sell_fill")
        connection.execute("RELEASE SAVEPOINT inventory_sell_fill")
        raise
