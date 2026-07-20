# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: revalue legacy commissions from exact Binance fill evidence.
"""Preview and atomically apply exact commission provenance repairs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import sqlite3
from typing import Callable, Mapping, Sequence

from ladder_dragon.execution.trade_accounting import TradeExecution, decimal_text


@dataclass(frozen=True)
class CommissionRepair:
    row_id: int
    symbol: str
    trade_id: int
    side: str
    price_text: str
    gross_qty: str
    timestamp: int
    net_qty: str
    commission_asset: str
    commission_amount: str
    commission_quote: str
    commission_value_status: str


@dataclass(frozen=True)
class CommissionRevaluation:
    repairs: tuple[CommissionRepair, ...]
    unresolved: tuple[str, ...]


def legacy_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return commission rows that still lack exact provenance."""
    connection.row_factory = sqlite3.Row
    return list(
        connection.execute(
            "SELECT id,symbol,side,price_text,gross_qty,ts,trade_id "
            "FROM trades WHERE LOWER(COALESCE(commission_value_status,'')) "
            "IN ('','legacy','unpriced') ORDER BY symbol,trade_id,id"
        )
    )


def build_revaluation(
    rows: Sequence[sqlite3.Row],
    exchange_trades: Mapping[str, Mapping[int, Mapping[str, object]]],
    *,
    value_commission: Callable[
        [str, str, Decimal, Decimal, int], tuple[Decimal | None, str]
    ],
) -> CommissionRevaluation:
    """Build repairs only from exchange fills that exactly match local rows."""
    repairs: list[CommissionRepair] = []
    unresolved: list[str] = []
    for row in rows:
        symbol = str(row["symbol"]).upper()
        trade_id = row["trade_id"]
        label = f"row={row['id']} symbol={symbol} trade_id={trade_id}"
        if trade_id is None:
            unresolved.append(f"{label}: missing exchange trade ID")
            continue
        trade = exchange_trades.get(symbol, {}).get(int(trade_id))
        if trade is None:
            unresolved.append(f"{label}: Binance fill not found")
            continue
        try:
            is_buyer = trade["isBuyer"]
            if not isinstance(is_buyer, bool):
                raise ValueError("isBuyer is not boolean")
            side = "BUY" if is_buyer else "SELL"
            price = Decimal(str(trade["price"]))
            gross_qty = Decimal(str(trade["qty"]))
            timestamp = int(trade["time"])
            if side != str(row["side"]).upper():
                raise ValueError("side mismatch")
            if price != Decimal(str(row["price_text"])):
                raise ValueError("price mismatch")
            if gross_qty != Decimal(str(row["gross_qty"])):
                raise ValueError("quantity mismatch")
            if timestamp != int(row["ts"]):
                raise ValueError("timestamp mismatch")
            commission_asset = str(trade.get("commissionAsset") or "").upper()
            commission_amount = Decimal(str(trade.get("commission", "0") or "0"))
            commission_quote, status = value_commission(
                symbol,
                commission_asset,
                commission_amount,
                price,
                timestamp,
            )
            if (
                commission_quote is None
                or not commission_quote.is_finite()
                or commission_quote < 0
                or status not in {"none", "exact", "converted"}
            ):
                raise ValueError(f"{commission_asset or 'unknown'} commission is unpriced")
            execution = TradeExecution.create(
                symbol=symbol,
                side=side,
                price=price,
                gross_qty=gross_qty,
                commission_asset=commission_asset,
                commission_amount=commission_amount,
                commission_quote=commission_quote,
                commission_value_status=status,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            unresolved.append(f"{label}: {exc}")
            continue
        repairs.append(
            CommissionRepair(
                row_id=int(row["id"]),
                symbol=symbol,
                trade_id=int(trade_id),
                side=side,
                price_text=str(row["price_text"]),
                gross_qty=str(row["gross_qty"]),
                timestamp=timestamp,
                net_qty=decimal_text(execution.net_qty),
                commission_asset=commission_asset,
                commission_amount=decimal_text(commission_amount),
                commission_quote=decimal_text(commission_quote),
                commission_value_status=status,
            )
        )
    return CommissionRevaluation(tuple(repairs), tuple(unresolved))


def apply_revaluation(
    connection: sqlite3.Connection,
    revaluation: CommissionRevaluation,
    *,
    recalculate_inventory: Callable[[sqlite3.Connection, str], None],
) -> int:
    """Apply a fully resolved revaluation in one immediate transaction."""
    if revaluation.unresolved:
        raise RuntimeError("unresolved commission rows prevent apply")
    legacy_real = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(trades)")
    }
    has_fee_real = "fee_quote" in legacy_real
    connection.execute("BEGIN IMMEDIATE")
    try:
        for repair in revaluation.repairs:
            assignments = (
                "net_qty=?,commission_asset=?,commission_amount=?,"
                "commission_quote=?,commission_value_status=?"
            )
            params: list[object] = [
                repair.net_qty,
                repair.commission_asset,
                repair.commission_amount,
                repair.commission_quote,
                repair.commission_value_status,
            ]
            if has_fee_real:
                assignments += ",fee_quote=?"
                params.append(float(Decimal(repair.commission_quote)))
            params.extend(
                (
                    repair.row_id,
                    repair.symbol,
                    repair.trade_id,
                    repair.side,
                    repair.price_text,
                    repair.gross_qty,
                    repair.timestamp,
                )
            )
            cursor = connection.execute(
                f"UPDATE trades SET {assignments} WHERE id=? AND symbol=? "
                "AND trade_id=? AND side=? AND CAST(price_text AS TEXT)=? "
                "AND CAST(gross_qty AS TEXT)=? AND ts=? "
                "AND LOWER(COALESCE(commission_value_status,'')) "
                "IN ('','legacy','unpriced')",
                params,
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"commission row changed before apply: {repair.symbol} "
                    f"trade_id={repair.trade_id}"
                )
        for symbol in sorted({repair.symbol for repair in revaluation.repairs}):
            recalculate_inventory(connection, symbol)
        connection.commit()
    except (ArithmeticError, RuntimeError, TypeError, ValueError, sqlite3.Error):
        connection.rollback()
        raise
    return len(revaluation.repairs)
