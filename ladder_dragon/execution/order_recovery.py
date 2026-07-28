# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the order recovery component of the execution layer.
"""Ladder Dragon order recovery support."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Iterable, Iterator


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
ORDER_JOURNAL_SCHEMA_VERSION = 3


def _decimal_text(value: object, *, field: str) -> str:
    """Return an exact, finite, non-negative canonical decimal string."""
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return format(number, "f")


def _price_text(value: object) -> str:
    """Canonicalize a limit price or the non-financial MARKET sentinel."""
    if str(value).upper() == "MARKET":
        return "MARKET"
    return _decimal_text(value, field="price")


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
            lifecycle_table = con.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'order_lifecycle_closures'"
            ).fetchone()
            lifecycle_counts = None
            if lifecycle_table is not None:
                lifecycle_counts = con.execute(
                    "SELECT COUNT(*) AS closed_exact, "
                    "SUM(CASE WHEN exit_reason = 'TP' THEN 1 ELSE 0 END) AS tp, "
                    "SUM(CASE WHEN exit_reason = 'STOP' THEN 1 ELSE 0 END) AS stop "
                    "FROM order_lifecycle_closures"
                ).fetchone()
            partial_exit_table = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'order_partial_protection_exits'"
            ).fetchone()
            if partial_exit_table is not None:
                managed_rows = con.execute(
                    "SELECT client_order_id, symbol, state, executed_qty "
                    "FROM order_intents WHERE side = 'BUY' AND state IN "
                    "('PARTIALLY_FILLED','FILLED','PROTECTION_PENDING','PROTECTED')"
                ).fetchall()
                partial_exit_rows = con.execute(
                    "SELECT parent_client_order_id, executed_qty "
                    "FROM order_partial_protection_exits"
                ).fetchall()
            else:
                managed_rows = con.execute(
                    "SELECT client_order_id, symbol, state, executed_qty "
                    "FROM order_intents WHERE side = 'BUY' AND state IN "
                    "('PARTIALLY_FILLED','FILLED','PROTECTION_PENDING','PROTECTED')"
                ).fetchall()
                partial_exit_rows = []
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
    if lifecycle_counts is not None:
        lifecycle["closed_exact"] = int(lifecycle_counts["closed_exact"] or 0)
        lifecycle["tp"] = int(lifecycle_counts["tp"] or 0)
        lifecycle["stop"] = int(lifecycle_counts["stop"] or 0)
    lifecycle["promotion_ready"] = lifecycle["closed_exact"] >= lifecycle["required"]
    exited_by_parent: dict[str, Decimal] = {}
    for row in partial_exit_rows:
        try:
            exited = Decimal(str(row["executed_qty"]))
        except (ArithmeticError, TypeError, ValueError):
            continue
        if not exited.is_finite() or exited <= 0:
            continue
        parent_id = str(row["parent_client_order_id"] or "")
        exited_by_parent[parent_id] = (
            exited_by_parent.get(parent_id, Decimal("0")) + exited
        )
    managed: dict[str, dict[str, Any]] = {}
    for row in managed_rows:
        symbol = str(row["symbol"] or "").upper()
        if not symbol:
            continue
        try:
            quantity = Decimal(str(row["executed_qty"] or "0")) - exited_by_parent.get(
                str(row["client_order_id"] or ""),
                Decimal("0"),
            )
        except (ArithmeticError, TypeError, ValueError):
            continue
        if quantity <= 0:
            continue
        entry = managed.setdefault(
            symbol,
            {"symbol": symbol, "quantity": Decimal("0"), "protected_buys": 0},
        )
        entry["quantity"] += quantity
        if str(row["state"]).upper() == "PROTECTED":
            entry["protected_buys"] += 1
    managed_buys = [
        {
            "symbol": entry["symbol"],
            "quantity": format(entry["quantity"], "f"),
            "protected_buys": entry["protected_buys"],
        }
        for entry in managed.values()
    ]
    return {
        "available": True,
        "counts": counts,
        "cancelled": cancelled,
        "pending": pending,
        "latest": item,
        "lifecycle": lifecycle,
        "managed_buys": managed_buys,
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
    """Represent OrderIntent."""
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
    """Represent OrderJournal."""

    def __init__(self, path: str | Path, *, venue: str = "testnet") -> None:
        self.path = Path(path)
        self.venue = venue
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._connection_pid: int | None = None
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Return one process-local connection instead of reopening per event."""
        pid = os.getpid()
        if self._connection is not None and self._connection_pid == pid:
            return self._connection
        if self._connection is not None:
            self._connection.close()
        con = sqlite3.connect(
            self.path,
            timeout=10,
            check_same_thread=False,
            isolation_level=None,
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=10000")
        # FULL + WAL make the journal durable. WAL is selected once per
        # process connection, not on every read and update.
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA foreign_keys=ON")
        self._connection = con
        self._connection_pid = pid
        return con

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = self._connect()
            if write:
                con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                if write and con.in_transaction:
                    con.rollback()
                raise
            else:
                if write and con.in_transaction:
                    con.commit()

    def close(self) -> None:
        """Close the process-local journal connection."""
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
                self._connection_pid = None

    def _init_schema(self) -> None:
        with self._session(write=True) as con:
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
                CREATE TABLE IF NOT EXISTS order_intent_legs (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    order_id INTEGER NOT NULL,
                    protection_client_order_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    leg_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (venue, symbol, order_id),
                    FOREIGN KEY (protection_client_order_id)
                        REFERENCES order_intents(client_order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_order_intent_legs_protection
                    ON order_intent_legs(protection_client_order_id);
                CREATE TABLE IF NOT EXISTS order_lifecycle_closures (
                    protection_client_order_id TEXT PRIMARY KEY,
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    parent_client_order_id TEXT NOT NULL,
                    exit_order_id INTEGER NOT NULL,
                    exit_reason TEXT NOT NULL CHECK(exit_reason IN ('TP', 'STOP')),
                    closed_at REAL NOT NULL,
                    FOREIGN KEY (protection_client_order_id)
                        REFERENCES order_intents(client_order_id),
                    FOREIGN KEY (parent_client_order_id)
                        REFERENCES order_intents(client_order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_order_lifecycle_reason
                    ON order_lifecycle_closures(venue, symbol, exit_reason, closed_at);
                CREATE TABLE IF NOT EXISTS order_partial_protection_exits (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    exit_order_id INTEGER NOT NULL,
                    protection_client_order_id TEXT NOT NULL,
                    parent_client_order_id TEXT NOT NULL,
                    exit_reason TEXT NOT NULL CHECK(exit_reason IN ('TP', 'STOP')),
                    executed_qty TEXT NOT NULL,
                    terminal_status TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    PRIMARY KEY (venue, symbol, exit_order_id),
                    FOREIGN KEY (protection_client_order_id)
                        REFERENCES order_intents(client_order_id),
                    FOREIGN KEY (parent_client_order_id)
                        REFERENCES order_intents(client_order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_partial_protection_parent
                    ON order_partial_protection_exits(
                        venue, parent_client_order_id
                    );
                CREATE TABLE IF NOT EXISTS order_journal_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
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
            version_row = con.execute(
                "SELECT value FROM order_journal_meta WHERE key = 'schema_version'"
            ).fetchone()
            version = int(version_row["value"]) if version_row is not None else 1
            if version < ORDER_JOURNAL_SCHEMA_VERSION:
                self._backfill_normalized_evidence(con)
                con.execute(
                    "INSERT INTO order_journal_meta(key, value) VALUES"
                    "('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(ORDER_JOURNAL_SCHEMA_VERSION),),
                )

    def _backfill_normalized_evidence(self, con: sqlite3.Connection) -> None:
        """Migrate legacy JSON evidence once, preserving exact history."""
        rows = con.execute(
            "SELECT * FROM order_intents "
            "WHERE order_type IN ('OCO', 'OTOCO') AND side = 'SELL'"
        ).fetchall()
        for row in rows:
            intent = self._from_row(row)
            if intent is None:
                continue
            legs = (intent.metadata or {}).get("verified_legs", [])
            if isinstance(legs, list) and len(legs) == 2:
                self._store_legs(con, intent, legs)
            metadata = intent.metadata or {}
            reason = str(metadata.get("exit_reason") or "").upper()
            exit_order_id = metadata.get("exit_order_id")
            if (
                intent.state == "CLOSED"
                and intent.parent_client_order_id
                and metadata.get("exact_lifecycle")
                and reason in {"TP", "STOP"}
                and exit_order_id is not None
            ):
                con.execute(
                    "INSERT OR IGNORE INTO order_lifecycle_closures "
                    "(protection_client_order_id, venue, symbol, "
                    "parent_client_order_id, exit_order_id, exit_reason, closed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        intent.client_order_id,
                        self.venue,
                        intent.symbol,
                        intent.parent_client_order_id,
                        int(exit_order_id),
                        reason,
                        float(metadata.get("closed_at") or time.time()),
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
        normalized = {
            "venue": self.venue,
            "symbol": symbol.upper(),
            "side": side.upper(),
            "purpose": purpose,
            "order_type": order_type.upper(),
            "quantity": _decimal_text(quantity, field="quantity"),
            "price": _price_text(price),
            "parent_client_order_id": parent_client_order_id,
            "metadata_json": json.dumps(
                metadata or {}, sort_keys=True, separators=(",", ":")
            ),
        }
        with self._session(write=True) as con:
            inserted = con.execute(
                """
                INSERT OR IGNORE INTO order_intents (
                    client_order_id, venue, symbol, side, purpose, order_type,
                    quantity, price, state, parent_client_order_id,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?, ?, ?)
                """,
                (
                    client_order_id,
                    normalized["venue"],
                    normalized["symbol"],
                    normalized["side"],
                    normalized["purpose"],
                    normalized["order_type"],
                    normalized["quantity"],
                    normalized["price"],
                    normalized["parent_client_order_id"],
                    normalized["metadata_json"],
                    now,
                    now,
                ),
            ).rowcount
            row = con.execute(
                "SELECT * FROM order_intents WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
            if inserted == 0 and row is not None:
                mismatches: list[str] = []
                for field in (
                    "venue",
                    "symbol",
                    "side",
                    "purpose",
                    "order_type",
                    "parent_client_order_id",
                ):
                    if row[field] != normalized[field]:
                        mismatches.append(field)
                try:
                    existing_metadata = json.loads(row["metadata_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    existing_metadata = object()
                if existing_metadata != (metadata or {}):
                    mismatches.append("metadata")
                for field in ("quantity", "price"):
                    try:
                        equal = (
                            str(row[field]).upper() == "MARKET"
                            and normalized[field] == "MARKET"
                        ) or (
                            Decimal(str(row[field])) == Decimal(normalized[field])
                        )
                    except (ArithmeticError, TypeError, ValueError):
                        equal = False
                    if not equal:
                        mismatches.append(field)
                if mismatches:
                    # Report only field names: metadata may contain private
                    # diagnostics and must never enter logs through exceptions.
                    raise ValueError(
                        "client_order_id conflicts with immutable fields: "
                        + ", ".join(sorted(mismatches))
                    )
        intent = self._from_row(row)
        if intent is None:
            raise RuntimeError(f"failed to persist order intent {client_order_id}")
        return intent

    def get(self, client_order_id: str) -> OrderIntent | None:
        with self._session() as con:
            row = con.execute(
                "SELECT * FROM order_intents WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        return self._from_row(row)

    def get_by_exchange_order_id(self, exchange_order_id: int) -> OrderIntent | None:
        with self._session() as con:
            row = con.execute(
                "SELECT * FROM order_intents WHERE exchange_order_id = ?",
                (int(exchange_order_id),),
            ).fetchone()
        return self._from_row(row)

    def created_at_ms_for_exchange_order(self, exchange_order_id: int) -> int | None:
        """Return the durable pre-POST wall-clock timestamp for one exact order."""
        with self._session() as con:
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
        with self._session() as con:
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
        self,
        exchange_order_id: int,
        *,
        symbol: str | None = None,
    ) -> tuple[OrderIntent, str] | None:
        """Resolve an exact OCO leg through the indexed normalized table."""
        params: list[Any] = [self.venue, int(exchange_order_id)]
        symbol_clause = ""
        if symbol:
            symbol_clause = " AND legs.symbol = ?"
            params.append(symbol.upper())
        with self._session() as con:
            rows = con.execute(
                "SELECT intents.*, legs.leg_type AS normalized_leg_type "
                "FROM order_intent_legs AS legs "
                "JOIN order_intents AS intents "
                "ON intents.client_order_id = legs.protection_client_order_id "
                "WHERE legs.venue = ? AND legs.order_id = ?"
                + symbol_clause,
                params,
            ).fetchall()
        if len(rows) > 1:
            raise RuntimeError("ambiguous protection leg identity")
        if not rows:
            return None
        return self._from_row(rows[0]), str(rows[0]["normalized_leg_type"]).upper()

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
        requested_quantity = Decimal(_decimal_text(quantity, field="quantity"))
        requested_price_text = _price_text(price)
        params: list[Any] = [
            self.venue,
            symbol.upper(),
            side.upper(),
            purpose,
            *states,
        ]
        with self._session() as con:
            rows = con.execute(
                f"""
                SELECT * FROM order_intents
                WHERE venue = ? AND symbol = ? AND side = ? AND purpose = ?
                  AND state IN ({placeholders})
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        for row in rows:
            try:
                price_matches = (
                    str(row["price"]).upper() == "MARKET"
                    and requested_price_text == "MARKET"
                ) or (
                    requested_price_text != "MARKET"
                    and Decimal(str(row["price"])) == Decimal(requested_price_text)
                )
                same = (
                    Decimal(str(row["quantity"])) == requested_quantity
                    and price_matches
                )
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "active journal intent contains invalid decimal fields"
                ) from exc
            if same:
                return self._from_row(row)
        return None

    @staticmethod
    def _row(con: sqlite3.Connection, client_order_id: str) -> sqlite3.Row:
        row = con.execute(
            "SELECT * FROM order_intents WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown order intent {client_order_id}")
        return row

    @staticmethod
    def _update_row(
        con: sqlite3.Connection,
        client_order_id: str,
        values: dict[str, Any],
    ) -> sqlite3.Row:
        allowed = {
            "state",
            "exchange_order_id",
            "exchange_order_list_id",
            "executed_qty",
            "cumulative_quote_qty",
            "metadata_json",
            "last_error",
            "updated_at",
        }
        invalid = set(values) - allowed
        if invalid:
            raise ValueError(f"unsupported journal fields: {sorted(invalid)}")
        values = {**values, "updated_at": time.time()}
        assignments = ", ".join(f"{name} = ?" for name in values)
        cur = con.execute(
            f"UPDATE order_intents SET {assignments} WHERE client_order_id = ?",
            [*values.values(), client_order_id],
        )
        if cur.rowcount != 1:
            raise KeyError(f"unknown order intent {client_order_id}")
        return OrderJournal._row(con, client_order_id)

    def _update(self, client_order_id: str, **values: Any) -> OrderIntent:
        with self._session(write=True) as con:
            row = self._update_row(con, client_order_id, values)
        intent = self._from_row(row)
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
        with self._session(write=True) as con:
            current = self._from_row(self._row(con, client_order_id))
            if current is None:
                raise KeyError(f"unknown order intent {client_order_id}")
            metadata = dict(current.metadata or {})
            metadata.update(values)
            row = self._update_row(
                con,
                client_order_id,
                {
                    "metadata_json": json.dumps(
                        metadata, sort_keys=True, separators=(",", ":")
                    )
                },
            )
        updated = self._from_row(row)
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
        """Atomically mark a protection intent and its exact parent protected."""
        child_values: dict[str, Any] = {
            "state": "PROTECTED",
            "last_error": None,
        }
        if order_list_id is not None:
            child_values["exchange_order_list_id"] = int(order_list_id)
        if exchange_order_id is not None:
            child_values["exchange_order_id"] = int(exchange_order_id)
        with self._session(write=True) as con:
            child = self._from_row(self._row(con, protection_client_order_id))
            if child is None or child.parent_client_order_id != parent_client_order_id:
                raise RuntimeError("protection parent identity mismatch")
            self._update_row(con, protection_client_order_id, child_values)
            self._update_row(
                con,
                parent_client_order_id,
                {"state": "PROTECTED", "last_error": None},
            )

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
        with self._session(write=True) as con:
            protection = self._from_row(
                self._row(con, protection_client_order_id)
            )
            if protection is None:
                raise KeyError(f"unknown order intent {protection_client_order_id}")
            sanitized = self._store_legs(con, protection, legs)
            metadata = dict(protection.metadata or {})
            metadata["verified_legs"] = sanitized
            row = self._update_row(
                con,
                protection_client_order_id,
                {
                    "metadata_json": json.dumps(
                        metadata, sort_keys=True, separators=(",", ":")
                    )
                },
            )
        intent = self._from_row(row)
        if intent is None:
            raise RuntimeError("protection intent disappeared")
        return intent

    @staticmethod
    def _sanitize_legs(legs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            order_id = leg.get("orderId", leg.get("order_id"))
            if order_id is None:
                continue
            sanitized.append(
                {
                    "order_id": int(order_id),
                    "client_order_id": str(
                        leg.get("clientOrderId", leg.get("client_order_id")) or ""
                    ),
                    "leg_type": str(
                        leg.get("type", leg.get("leg_type")) or ""
                    ).upper(),
                }
            )
        if len(sanitized) != 2:
            raise RuntimeError("verified OCO must contain exactly two legs")
        if len({leg["order_id"] for leg in sanitized}) != 2:
            raise RuntimeError("verified OCO legs must have distinct order IDs")
        return sanitized

    def _store_legs(
        self,
        con: sqlite3.Connection,
        protection: OrderIntent,
        legs: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        sanitized = self._sanitize_legs(legs)
        now = time.time()
        for leg in sanitized:
            existing = con.execute(
                "SELECT protection_client_order_id, client_order_id, leg_type "
                "FROM order_intent_legs "
                "WHERE venue = ? AND symbol = ? AND order_id = ?",
                (self.venue, protection.symbol, leg["order_id"]),
            ).fetchone()
            expected = (
                protection.client_order_id,
                leg["client_order_id"],
                leg["leg_type"],
            )
            if existing is not None and tuple(existing) != expected:
                raise RuntimeError("OCO leg identity conflicts with journal history")
            con.execute(
                "INSERT OR IGNORE INTO order_intent_legs "
                "(venue, symbol, order_id, protection_client_order_id, "
                "client_order_id, leg_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self.venue,
                    protection.symbol,
                    leg["order_id"],
                    protection.client_order_id,
                    leg["client_order_id"],
                    leg["leg_type"],
                    now,
                ),
            )
        return sanitized

    def mark_verified_protected(
        self,
        *,
        parent_client_order_id: str,
        protection_client_order_id: str,
        legs: Iterable[dict[str, Any]],
        order_list_id: int | None = None,
        exchange_order_id: int | None = None,
    ) -> None:
        """Persist verified legs and both protected states in one transaction."""
        with self._session(write=True) as con:
            protection = self._from_row(
                self._row(con, protection_client_order_id)
            )
            if (
                protection is None
                or protection.parent_client_order_id != parent_client_order_id
            ):
                raise RuntimeError("protection parent identity mismatch")
            sanitized = self._store_legs(con, protection, legs)
            metadata = dict(protection.metadata or {})
            metadata["verified_legs"] = sanitized
            child_values: dict[str, Any] = {
                "state": "PROTECTED",
                "last_error": None,
                "metadata_json": json.dumps(
                    metadata, sort_keys=True, separators=(",", ":")
                ),
            }
            if order_list_id is not None:
                child_values["exchange_order_list_id"] = int(order_list_id)
            if exchange_order_id is not None:
                child_values["exchange_order_id"] = int(exchange_order_id)
            self._update_row(con, protection_client_order_id, child_values)
            self._update_row(
                con,
                parent_client_order_id,
                {"state": "PROTECTED", "last_error": None},
            )

    def mark_exact_lifecycle_closed(
        self,
        *,
        protection_client_order_id: str,
        exit_order_id: int,
        exit_reason: str,
    ) -> None:
        """Close a BUY/OCO lifecycle after an exact terminal TP/STOP fill."""
        reason = str(exit_reason).upper()
        if reason not in {"TP", "STOP"}:
            raise ValueError("exit reason must be TP or STOP")
        with self._session(write=True) as con:
            protection = self._from_row(
                self._row(con, protection_client_order_id)
            )
            if protection is None or not protection.parent_client_order_id:
                raise RuntimeError("protection has no exact parent BUY")
            parent = self._from_row(
                self._row(con, protection.parent_client_order_id)
            )
            if parent is None:
                raise RuntimeError("protection parent BUY is unavailable")
            leg = con.execute(
                "SELECT leg_type FROM order_intent_legs "
                "WHERE venue = ? AND symbol = ? AND order_id = ? "
                "AND protection_client_order_id = ?",
                (
                    self.venue,
                    protection.symbol,
                    int(exit_order_id),
                    protection_client_order_id,
                ),
            ).fetchone()
            if leg is None:
                raise RuntimeError("exit order is not a verified protection leg")
            leg_type = str(leg["leg_type"] or "").upper()
            if reason == "STOP" and "STOP" not in leg_type:
                raise RuntimeError("STOP closure does not match verified leg type")
            if reason == "TP" and "STOP" in leg_type:
                raise RuntimeError("TP closure does not match verified leg type")
            existing = con.execute(
                "SELECT exit_order_id, exit_reason FROM order_lifecycle_closures "
                "WHERE protection_client_order_id = ?",
                (protection_client_order_id,),
            ).fetchone()
            if existing is not None and (
                int(existing["exit_order_id"]) != int(exit_order_id)
                or str(existing["exit_reason"]) != reason
            ):
                raise RuntimeError("lifecycle closure conflicts with journal history")
            closed_at = time.time()
            metadata_update = {
                "exact_lifecycle": True,
                "exit_order_id": int(exit_order_id),
                "exit_reason": reason,
                "closed_at": closed_at,
            }
            for intent in (protection, parent):
                metadata = dict(intent.metadata or {})
                metadata.update(metadata_update)
                self._update_row(
                    con,
                    intent.client_order_id,
                    {
                        "state": "CLOSED",
                        "last_error": None,
                        "metadata_json": json.dumps(
                            metadata, sort_keys=True, separators=(",", ":")
                        ),
                    },
                )
            con.execute(
                "INSERT OR IGNORE INTO order_lifecycle_closures "
                "(protection_client_order_id, venue, symbol, "
                "parent_client_order_id, exit_order_id, exit_reason, closed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    protection_client_order_id,
                    self.venue,
                    protection.symbol,
                    protection.parent_client_order_id,
                    int(exit_order_id),
                    reason,
                    closed_at,
                ),
            )

    def record_partial_protection_exit(
        self,
        *,
        protection_client_order_id: str,
        exit_order_id: int,
        exit_reason: str,
        executed_qty: object,
        terminal_status: str,
    ) -> None:
        """Record a terminal partial TP/STOP and reopen only the residual lot."""
        reason = str(exit_reason).upper()
        status = str(terminal_status).upper()
        quantity = _decimal_text(executed_qty, field="executed_qty")
        if reason not in {"TP", "STOP"}:
            raise ValueError("exit reason must be TP or STOP")
        if Decimal(quantity) <= 0:
            raise ValueError("partial protection exit quantity must be positive")
        if status not in TERMINAL_EXCHANGE_STATES:
            raise ValueError("partial protection exit must be terminal")
        with self._session(write=True) as con:
            protection = self._from_row(
                self._row(con, protection_client_order_id)
            )
            if protection is None or not protection.parent_client_order_id:
                raise RuntimeError("partial exit protection has no parent BUY")
            parent = self._from_row(
                self._row(con, protection.parent_client_order_id)
            )
            if parent is None:
                raise RuntimeError("partial exit parent BUY is unavailable")
            leg = con.execute(
                "SELECT leg_type FROM order_intent_legs "
                "WHERE venue = ? AND symbol = ? AND order_id = ? "
                "AND protection_client_order_id = ?",
                (
                    self.venue,
                    protection.symbol,
                    int(exit_order_id),
                    protection_client_order_id,
                ),
            ).fetchone()
            if leg is None:
                raise RuntimeError("partial exit is not a verified protection leg")
            leg_type = str(leg["leg_type"] or "").upper()
            if reason == "STOP" and "STOP" not in leg_type:
                raise RuntimeError("partial STOP does not match verified leg type")
            if reason == "TP" and "STOP" in leg_type:
                raise RuntimeError("partial TP does not match verified leg type")
            expected = (
                protection_client_order_id,
                protection.parent_client_order_id,
                reason,
                quantity,
                status,
            )
            existing = con.execute(
                "SELECT protection_client_order_id, parent_client_order_id, "
                "exit_reason, executed_qty, terminal_status "
                "FROM order_partial_protection_exits "
                "WHERE venue = ? AND symbol = ? AND exit_order_id = ?",
                (self.venue, protection.symbol, int(exit_order_id)),
            ).fetchone()
            if existing is not None and tuple(existing) != expected:
                raise RuntimeError(
                    "partial protection exit conflicts with journal history"
                )
            con.execute(
                "INSERT OR IGNORE INTO order_partial_protection_exits "
                "(venue, symbol, exit_order_id, protection_client_order_id, "
                "parent_client_order_id, exit_reason, executed_qty, "
                "terminal_status, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.venue,
                    protection.symbol,
                    int(exit_order_id),
                    protection_client_order_id,
                    protection.parent_client_order_id,
                    reason,
                    quantity,
                    status,
                    time.time(),
                ),
            )
            diagnostic = (
                f"terminal partial {reason} exit {exit_order_id} executed "
                f"{quantity}; residual protection required"
            )
            self._update_row(
                con,
                protection_client_order_id,
                {"state": "FAILED", "last_error": diagnostic},
            )
            self._update_row(
                con,
                protection.parent_client_order_id,
                {"state": "PROTECTION_PENDING", "last_error": diagnostic},
            )

    def partial_protection_exit_quantity(
        self,
        parent_client_order_id: str,
    ) -> Decimal:
        """Return the idempotent sum already exited by terminal partial legs."""
        with self._session() as con:
            rows = con.execute(
                "SELECT executed_qty FROM order_partial_protection_exits "
                "WHERE venue = ? AND parent_client_order_id = ?",
                (self.venue, parent_client_order_id),
            ).fetchall()
        total = Decimal("0")
        for row in rows:
            try:
                quantity = Decimal(str(row["executed_qty"]))
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "partial protection exit contains invalid quantity"
                ) from exc
            if not quantity.is_finite() or quantity <= 0:
                raise RuntimeError(
                    "partial protection exit contains invalid quantity"
                )
            total += quantity
        return total

    def unresolved_buys(self, symbol: str | None = None) -> list[OrderIntent]:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        params: list[Any] = [self.venue, *ACTIVE_STATES]
        where_symbol = ""
        if symbol:
            where_symbol = " AND symbol = ?"
            params.append(symbol.upper())
        with self._session() as con:
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

    def protected_buys(self, symbol: str | None = None) -> list[OrderIntent]:
        """Return BUY parents whose exchange protection must still be live."""
        params: list[Any] = [self.venue]
        where_symbol = ""
        if symbol:
            where_symbol = " AND symbol = ?"
            params.append(symbol.upper())
        with self._session() as con:
            rows: Iterable[sqlite3.Row] = con.execute(
                f"""
                SELECT * FROM order_intents
                WHERE venue = ? AND side = 'BUY' AND state = 'PROTECTED'
                {where_symbol}
                ORDER BY created_at
                """,
                params,
            ).fetchall()
        return [
            intent
            for row in rows
            if (intent := self._from_row(row)) is not None
        ]

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
        with self._session() as con:
            rows: Iterable[sqlite3.Row] = con.execute(
                f"""
                SELECT * FROM order_intents
                WHERE venue = ? AND state IN ({placeholders})
                  AND order_type NOT IN ('OCO', 'OTOCO')
                {where_symbol}
                ORDER BY created_at
                """,
                params,
            ).fetchall()
        return [intent for row in rows if (intent := self._from_row(row)) is not None]
