# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the order recovery component of the execution layer.
"""Постоянный журнал намерений и безопасная сверка ордеров после рестарта."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import json
import re
import sqlite3
import time
from typing import Any, Iterable


ACTIVE_STATES = (
    "PREPARED",
    "UNKNOWN",
    "SUBMITTED",
    "PARTIALLY_FILLED",
    "FILLED",
    "PROTECTION_PENDING",
)
SELL_ACTIVE_STATES = (
    "PREPARED",
    "UNKNOWN",
    "SUBMITTED",
    "PARTIALLY_FILLED",
    "PROTECTED",
)
TERMINAL_EXCHANGE_STATES = {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"}
TERMINAL_JOURNAL_STATES = {
    "FILLED",
    "CLOSED",
    "PROTECTED",
    "CANCELED",
    "CANCELLED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
    "REJECTED",
    "FAILED",
}
_SIGNED_BINANCE_URL_RE = re.compile(
    r"(https://(?:[A-Za-z0-9.-]*\.)?binance\.(?:com|vision)/[^\s?]+)\?[^\s;]+",
    re.IGNORECASE,
)
_SIGNATURE_PARAM_RE = re.compile(r"(signature=)[^&\s;]+", re.IGNORECASE)


def _safe_error_text(error: object) -> str:
    """Remove signed Binance query data before persisting an error."""
    text = str(error)
    text = _SIGNED_BINANCE_URL_RE.sub(r"\1?<redacted>", text)
    text = _SIGNATURE_PARAM_RE.sub(r"\1<redacted>", text)
    return text[:1000]


def read_order_journal_telemetry(path: str | Path) -> dict[str, Any]:
    """Return a sanitized read-only journal summary for runtime telemetry.

    The trading process performs this read because it already owns the WAL/SHM
    files. The dashboard receives only aggregate states and the latest safe
    order fields; it never needs filesystem write access to the live database.
    """
    target = Path(path)
    if not target.exists():
        return {"available": False, "reason": "order journal not found"}
    try:
        with sqlite3.connect(
            f"file:{target}?mode=ro",
            uri=True,
            timeout=2,
        ) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=2000")
            columns = {
                str(row[1])
                for row in con.execute("PRAGMA table_info(order_intents)")
            }
            if not {"state", "updated_at"}.issubset(columns):
                return {
                    "available": False,
                    "reason": "order journal schema unavailable",
                }
            counts = {
                str(row["state"]): int(row["count"])
                for row in con.execute(
                    "SELECT state, COUNT(*) AS count "
                    "FROM order_intents GROUP BY state"
                )
            }
            latest = con.execute(
                "SELECT symbol, side, state, exchange_order_id, "
                "executed_qty, quantity, updated_at "
                "FROM order_intents ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            lifecycle_rows = con.execute(
                "SELECT metadata_json FROM order_intents "
                "WHERE side = 'BUY' AND state = 'CLOSED'"
            ).fetchall()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return {"available": False, "reason": type(exc).__name__}

    item: dict[str, Any] | None = None
    if latest is not None:
        try:
            executed_qty = Decimal(str(latest["executed_qty"] or "0"))
            requested_qty = Decimal(str(latest["quantity"] or "0"))
            partial_fill = (
                executed_qty > 0
                and requested_qty > 0
                and executed_qty < requested_qty
            )
        except (ArithmeticError, TypeError, ValueError):
            partial_fill = False
        try:
            updated_at_epoch: float | None = float(latest["updated_at"])
        except (ArithmeticError, TypeError, ValueError):
            updated_at_epoch = None
        item = {
            "symbol": latest["symbol"],
            "side": latest["side"],
            "status": latest["state"],
            "order_id": latest["exchange_order_id"],
            "executed_qty": latest["executed_qty"],
            "quantity": latest["quantity"],
            "partial_fill": partial_fill,
            "latency_ms": None,
            "commission_usdt": None,
            "updated_at_epoch": updated_at_epoch,
        }
    cancelled = sum(
        count for state, count in counts.items() if "CANCEL" in state.upper()
    )
    pending = sum(
        count
        for state, count in counts.items()
        if state.upper() not in TERMINAL_JOURNAL_STATES
    )
    lifecycle = {"closed_exact": 0, "tp": 0, "stop": 0, "required": 3}
    for row in lifecycle_rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        reason = str(metadata.get("exit_reason") or "").upper()
        if not metadata.get("exact_lifecycle") or reason not in {"TP", "STOP"}:
            continue
        lifecycle["closed_exact"] += 1
        lifecycle[reason.lower()] += 1
    lifecycle["promotion_ready"] = lifecycle["closed_exact"] >= lifecycle["required"]
    return {
        "available": True,
        "counts": counts,
        "cancelled": cancelled,
        "pending": pending,
        "latest": item,
        "lifecycle": lifecycle,
        "updated_at_epoch": time.time(),
    }


def read_order_observation(
    path: str | Path,
    exchange_order_id: int,
) -> dict[str, Any]:
    """Read only the allowlisted market-range diagnostics for one order."""
    target = Path(path)
    if not target.exists():
        return {}
    try:
        with sqlite3.connect(
            f"file:{target}?mode=ro",
            uri=True,
            timeout=2,
        ) as con:
            row = con.execute(
                """
                SELECT metadata_json FROM order_intents
                WHERE exchange_order_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (int(exchange_order_id),),
            ).fetchone()
        metadata = json.loads(row[0] or "{}") if row else {}
    except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError, ValueError):
        return {}
    allowed = {
        "market_first_price",
        "market_last_price",
        "market_min_price",
        "market_max_price",
        "market_observation_count",
        "market_first_observed_at",
        "market_last_observed_at",
    }
    return {key: metadata[key] for key in allowed if key in metadata}


@dataclass(frozen=True)
class OrderIntent:
    """Локальное намерение, связывающее действие бота с объектом Binance."""
    client_order_id: str
    symbol: str
    side: str
    purpose: str
    order_type: str
    quantity: str
    price: str
    state: str
    parent_client_order_id: str | None = None
    exchange_order_id: int | None = None
    exchange_order_list_id: int | None = None
    executed_qty: str = "0"
    cumulative_quote_qty: str = "0"
    metadata: dict[str, Any] | None = None
    last_error: str | None = None


class OrderJournal:
    """SQLite-журнал, записываемый до каждого изменяющего запроса к бирже.

    PREPARED фиксируется до POST. Поэтому после таймаута или рестарта можно
    запросить Binance по clientOrderId и не создать дублирующий ордер.
    """

    def __init__(self, path: str | Path, *, venue: str = "testnet") -> None:
        self.path = Path(path)
        self.venue = venue
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # FULL + WAL make the intent journal durable and allow recovery code
        # to read it while the executor is running.
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS order_intents (
                    client_order_id TEXT PRIMARY KEY,
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    state TEXT NOT NULL,
                    parent_client_order_id TEXT,
                    exchange_order_id INTEGER,
                    exchange_order_list_id INTEGER,
                    executed_qty TEXT NOT NULL DEFAULT '0',
                    cumulative_quote_qty TEXT NOT NULL DEFAULT '0',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_order_intents_active
                    ON order_intents(venue, symbol, side, purpose, state);
                CREATE INDEX IF NOT EXISTS idx_order_intents_exchange_order
                    ON order_intents(exchange_order_id);
                CREATE INDEX IF NOT EXISTS idx_order_intents_parent
                    ON order_intents(parent_client_order_id);
                """
            )
            # Older transport versions persisted requests.HTTPError verbatim,
            # including short-lived signed query strings. Scrub those rows as
            # soon as the journal is opened after an upgrade.
            rows = con.execute(
                """
                SELECT client_order_id, last_error
                FROM order_intents
                WHERE last_error LIKE '%signature=%'
                """
            ).fetchall()
            for row in rows:
                con.execute(
                    """
                    UPDATE order_intents SET last_error = ?
                    WHERE client_order_id = ?
                    """,
                    (
                        _safe_error_text(row["last_error"]),
                        row["client_order_id"],
                    ),
                )

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> OrderIntent | None:
        if row is None:
            return None
        raw_metadata = row["metadata_json"] or "{}"
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            metadata = {}
        return OrderIntent(
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            side=row["side"],
            purpose=row["purpose"],
            order_type=row["order_type"],
            quantity=row["quantity"],
            price=row["price"],
            state=row["state"],
            parent_client_order_id=row["parent_client_order_id"],
            exchange_order_id=row["exchange_order_id"],
            exchange_order_list_id=row["exchange_order_list_id"],
            executed_qty=row["executed_qty"],
            cumulative_quote_qty=row["cumulative_quote_qty"],
            metadata=metadata,
            last_error=row["last_error"],
        )

    def prepare(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: str,
        purpose: str,
        order_type: str,
        quantity: object,
        price: object = "0",
        parent_client_order_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OrderIntent:
        now = time.time()
        with self._connect() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO order_intents (
                    client_order_id, venue, symbol, side, purpose, order_type,
                    quantity, price, state, parent_client_order_id,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?, ?, ?)
                """,
                (
                    client_order_id,
                    self.venue,
                    symbol.upper(),
                    side.upper(),
                    purpose,
                    order_type.upper(),
                    str(quantity),
                    str(price),
                    parent_client_order_id,
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            row = con.execute(
                "SELECT * FROM order_intents WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        intent = self._from_row(row)
        if intent is None:
            raise RuntimeError(f"failed to persist order intent {client_order_id}")
        return intent

    def get(self, client_order_id: str) -> OrderIntent | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM order_intents WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        return self._from_row(row)

    def get_by_exchange_order_id(self, exchange_order_id: int) -> OrderIntent | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM order_intents WHERE exchange_order_id = ?",
                (int(exchange_order_id),),
            ).fetchone()
        return self._from_row(row)

    def created_at_ms_for_exchange_order(self, exchange_order_id: int) -> int | None:
        """Return the durable pre-POST wall-clock timestamp for one exact order."""
        with self._connect() as con:
            row = con.execute(
                "SELECT created_at FROM order_intents "
                "WHERE exchange_order_id = ? ORDER BY created_at DESC LIMIT 1",
                (int(exchange_order_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            created_at = Decimal(str(row["created_at"]))
        except (ArithmeticError, TypeError, ValueError):
            return None
        if not created_at.is_finite() or created_at <= 0:
            return None
        return int(created_at * Decimal("1000"))

    def protection_for_parent(self, parent_client_order_id: str) -> OrderIntent | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM order_intents
                WHERE parent_client_order_id = ? AND side = 'SELL'
                ORDER BY created_at DESC LIMIT 1
                """,
                (parent_client_order_id,),
            ).fetchone()
        return self._from_row(row)

    def protection_for_leg_order_id(
        self, exchange_order_id: int
    ) -> tuple[OrderIntent, str] | None:
        """Resolve an OCO leg only through its exact persisted exchange ID."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM order_intents WHERE order_type = 'OCO' "
                "AND side = 'SELL' ORDER BY created_at DESC"
            ).fetchall()
        target = int(exchange_order_id)
        for row in rows:
            intent = self._from_row(row)
            if intent is None:
                continue
            for leg in (intent.metadata or {}).get("verified_legs", []):
                try:
                    leg_order_id = int(leg.get("order_id"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if leg_order_id == target:
                    return intent, str(leg.get("leg_type") or "").upper()
        return None

    def find_active(
        self,
        *,
        symbol: str,
        side: str,
        purpose: str,
        quantity: object,
        price: object,
    ) -> OrderIntent | None:
        states = ACTIVE_STATES if side.upper() == "BUY" else SELL_ACTIVE_STATES
        placeholders = ",".join("?" for _ in states)
        params: list[Any] = [
            self.venue,
            symbol.upper(),
            side.upper(),
            purpose,
            str(quantity),
            str(price),
            *states,
        ]
        with self._connect() as con:
            row = con.execute(
                f"""
                SELECT * FROM order_intents
                WHERE venue = ? AND symbol = ? AND side = ? AND purpose = ?
                  AND quantity = ? AND price = ? AND state IN ({placeholders})
                ORDER BY created_at DESC LIMIT 1
                """,
                params,
            ).fetchone()
        return self._from_row(row)

    def _update(self, client_order_id: str, **values: Any) -> OrderIntent:
        allowed = {
            "state",
            "exchange_order_id",
            "exchange_order_list_id",
            "executed_qty",
            "cumulative_quote_qty",
            "last_error",
        }
        invalid = set(values) - allowed
        if invalid:
            raise ValueError(f"unsupported journal fields: {sorted(invalid)}")
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{name} = ?" for name in values)
        params = [*values.values(), client_order_id]
        with self._connect() as con:
            cur = con.execute(
                f"UPDATE order_intents SET {assignments} WHERE client_order_id = ?",
                params,
            )
            if cur.rowcount != 1:
                raise KeyError(f"unknown order intent {client_order_id}")
        intent = self.get(client_order_id)
        if intent is None:
            raise RuntimeError(f"order intent disappeared: {client_order_id}")
        return intent

    def update_metadata(
        self,
        client_order_id: str,
        values: dict[str, Any],
    ) -> OrderIntent:
        """Merge sanitized execution telemetry into an existing intent.

        Metadata is reserved for non-secret lifecycle diagnostics.  Keeping the
        observed market range beside the durable order intent lets cleanup after
        a restart explain why a passive order never traded.
        """
        intent = self.get(client_order_id)
        if intent is None:
            raise KeyError(f"unknown order intent {client_order_id}")
        metadata = dict(intent.metadata or {})
        metadata.update(values)
        with self._connect() as con:
            cur = con.execute(
                """
                UPDATE order_intents
                SET metadata_json = ?
                WHERE client_order_id = ?
                """,
                (
                    json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                    client_order_id,
                ),
            )
            if cur.rowcount != 1:
                raise KeyError(f"unknown order intent {client_order_id}")
        updated = self.get(client_order_id)
        if updated is None:
            raise RuntimeError(f"order intent disappeared: {client_order_id}")
        return updated

    def mark_unknown(self, client_order_id: str, error: object) -> OrderIntent:
        return self._update(
            client_order_id,
            state="UNKNOWN",
            last_error=_safe_error_text(error),
        )

    def record_exchange_order(
        self, client_order_id: str, payload: dict[str, Any]
    ) -> OrderIntent:
        exchange_status = str(payload.get("status") or "NEW").upper()
        if exchange_status == "NEW":
            state = "SUBMITTED"
        elif exchange_status == "PARTIALLY_FILLED":
            state = "PARTIALLY_FILLED"
        elif exchange_status == "FILLED":
            state = "FILLED"
        elif exchange_status in TERMINAL_EXCHANGE_STATES:
            state = (
                "PROTECTION_PENDING"
                if Decimal(str(payload.get("executedQty") or "0")) > 0
                else exchange_status
            )
        else:
            state = "UNKNOWN"
        return self._update(
            client_order_id,
            state=state,
            exchange_order_id=(
                int(payload["orderId"]) if payload.get("orderId") is not None else None
            ),
            executed_qty=str(payload.get("executedQty") or "0"),
            cumulative_quote_qty=str(payload.get("cummulativeQuoteQty") or "0"),
            last_error=None,
        )

    def record_order_list(
        self, client_order_id: str, payload: dict[str, Any]
    ) -> OrderIntent:
        list_status = str(payload.get("listStatusType") or "").upper()
        state = "FILLED" if list_status == "ALL_DONE" else "SUBMITTED"
        return self._update(
            client_order_id,
            state=state,
            exchange_order_list_id=(
                int(payload["orderListId"])
                if payload.get("orderListId") is not None
                else None
            ),
            last_error=None,
        )

    def mark_protection_pending(self, client_order_id: str) -> OrderIntent:
        return self._update(client_order_id, state="PROTECTION_PENDING", last_error=None)

    def mark_protected(
        self,
        *,
        parent_client_order_id: str,
        protection_client_order_id: str,
        order_list_id: int | None = None,
        exchange_order_id: int | None = None,
    ) -> None:
        child_values: dict[str, Any] = {
            "state": "PROTECTED",
            "last_error": None,
        }
        if order_list_id is not None:
            child_values["exchange_order_list_id"] = int(order_list_id)
        if exchange_order_id is not None:
            child_values["exchange_order_id"] = int(exchange_order_id)
        self._update(protection_client_order_id, **child_values)
        self._update(parent_client_order_id, state="PROTECTED", last_error=None)

    def mark_failed(self, client_order_id: str, error: object) -> OrderIntent:
        return self._update(
            client_order_id,
            state="FAILED",
            last_error=_safe_error_text(error),
        )

    def mark_closed(self, client_order_id: str) -> OrderIntent:
        """Mark an exactly reconciled lifecycle as terminally closed."""
        return self._update(client_order_id, state="CLOSED", last_error=None)

    def record_verified_protection_legs(
        self,
        protection_client_order_id: str,
        legs: Iterable[dict[str, Any]],
    ) -> OrderIntent:
        """Persist allowlisted OCO leg identities for exact fill attribution."""
        sanitized: list[dict[str, Any]] = []
        for leg in legs:
            if not isinstance(leg, dict) or leg.get("orderId") is None:
                continue
            sanitized.append(
                {
                    "order_id": int(leg["orderId"]),
                    "client_order_id": str(leg.get("clientOrderId") or ""),
                    "leg_type": str(leg.get("type") or "").upper(),
                }
            )
        if len(sanitized) != 2:
            raise RuntimeError("verified OCO must contain exactly two legs")
        return self.update_metadata(
            protection_client_order_id,
            {"verified_legs": sanitized},
        )

    def mark_exact_lifecycle_closed(
        self,
        *,
        protection_client_order_id: str,
        exit_order_id: int,
        exit_reason: str,
    ) -> None:
        """Close a BUY/OCO lifecycle after an exact terminal TP/STOP fill."""
        protection = self.get(protection_client_order_id)
        if protection is None or not protection.parent_client_order_id:
            raise RuntimeError("protection has no exact parent BUY")
        reason = str(exit_reason).upper()
        if reason not in {"TP", "STOP"}:
            raise ValueError("exit reason must be TP or STOP")
        metadata = {
            "exact_lifecycle": True,
            "exit_order_id": int(exit_order_id),
            "exit_reason": reason,
            "closed_at": time.time(),
        }
        self.update_metadata(protection_client_order_id, metadata)
        self.update_metadata(protection.parent_client_order_id, metadata)
        self.mark_closed(protection_client_order_id)
        self.mark_closed(protection.parent_client_order_id)

    def unresolved_buys(self, symbol: str | None = None) -> list[OrderIntent]:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        params: list[Any] = [self.venue, *ACTIVE_STATES]
        where_symbol = ""
        if symbol:
            where_symbol = " AND symbol = ?"
            params.append(symbol.upper())
        with self._connect() as con:
            rows: Iterable[sqlite3.Row] = con.execute(
                f"""
                SELECT * FROM order_intents
                WHERE venue = ? AND side = 'BUY' AND state IN ({placeholders})
                {where_symbol}
                ORDER BY created_at
                """,
                params,
            ).fetchall()
        return [intent for row in rows if (intent := self._from_row(row)) is not None]

    def nonterminal_orders(self, symbol: str | None = None) -> list[OrderIntent]:
        """Return ordinary exchange orders whose final state needs reconciliation."""
        # FILLED BUY protection and PROTECTED SELL/OCO recovery have dedicated
        # paths. Re-query only states whose exchange terminal status is unknown.
        states = (
            "PREPARED",
            "UNKNOWN",
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "PROTECTION_PENDING",
        )
        placeholders = ",".join("?" for _ in states)
        params: list[Any] = [self.venue, *states]
        where_symbol = ""
        if symbol:
            where_symbol = " AND symbol = ?"
            params.append(symbol.upper())
        with self._connect() as con:
            rows: Iterable[sqlite3.Row] = con.execute(
                f"""
                SELECT * FROM order_intents
                WHERE venue = ? AND state IN ({placeholders})
                  AND order_type != 'OCO'
                {where_symbol}
                ORDER BY created_at
                """,
                params,
            ).fetchall()
        return [intent for row in rows if (intent := self._from_row(row)) is not None]
