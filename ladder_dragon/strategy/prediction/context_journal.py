# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: retain bounded source-owned historical context without changing trading evidence.
"""Append-only context storage and read-only cutoff-safe replay export."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from ladder_dragon.persistence.sql_statements import execute_sql_script
from ladder_dragon.strategy.prediction.context_sources import context_from_sources, stamp, symbol_name
from ladder_dragon.strategy.prediction.historical_policy import fingerprint

MAX_RECORDS = 131_072
MAX_BYTES = 256 * 1024 * 1024
MAX_EXPORT_RECORDS = 4096
MAX_EXPORT_BYTES = 16 * 1024 * 1024
BLOCK_REASONS = {"SOURCE_UNAVAILABLE", "PANIC_UNAVAILABLE", "CLASSIFIER_MISMATCH", "OBSERVATION_SUPERSEDED"}
MIGRATION = Path(__file__).with_name("context_migrations") / "001_context.sql"


def _session(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("context session identity invalid")
    return value


def _validate_payload(payload: dict) -> None:
    if set(payload) != {"schema_version", "symbol", "session_id", "observed_at_ms", "status", "reason", "sources", "context"}:
        raise ValueError("context record schema differs")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("context record version differs")
    symbol_name(payload["symbol"])
    _session(payload["session_id"])
    stamp(payload["observed_at_ms"])
    if payload["status"] == "BLOCKED":
        if payload["reason"] not in BLOCK_REASONS or payload["sources"] or payload["context"] is not None:
            raise ValueError("context blocked record invalid")
    elif payload["status"] == "AVAILABLE":
        row = context_from_sources(payload["sources"], payload["observed_at_ms"])
        if row != payload["context"] or row["symbol"] != payload["symbol"] or payload["reason"] is not None:
            raise ValueError("context source projection differs")
    else:
        raise ValueError("context status unsupported")


class ContextJournal:
    """Check capacity on each write; never delete sources or pending evidence."""

    def __init__(self, path: Path, *, maximum_records: int = MAX_RECORDS, maximum_bytes: int = MAX_BYTES):
        self.path = Path(path)
        if (type(maximum_records) is not int or not 1 <= maximum_records <= MAX_RECORDS
                or type(maximum_bytes) is not int or not 65536 <= maximum_bytes <= MAX_BYTES):
            raise ValueError("context storage limits invalid")
        self.maximum_records, self.maximum_bytes = maximum_records, maximum_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            sql = MIGRATION.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode()).hexdigest()
            if version == 0:
                execute_sql_script(connection, sql)
                connection.execute("INSERT INTO context_schema VALUES(1,?)", (digest,))
                connection.execute("PRAGMA user_version=1")
            elif version != 1 or connection.execute("SELECT sha256 FROM context_schema WHERE version=1").fetchone() != (digest,):
                raise ValueError("context migration identity differs")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=1)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA wal_autocheckpoint=256")
            yield connection
            connection.commit()
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            connection.rollback()
            raise
        finally:
            connection.close()

    def append(self, *, symbol: str, session_id: str, observed_at_ms: int,
               sources: dict | None = None, reason: str | None = None) -> dict:
        payload = {"schema_version": 1, "symbol": symbol_name(symbol), "session_id": _session(session_id),
                   "observed_at_ms": stamp(observed_at_ms), "status": "BLOCKED" if reason else "AVAILABLE",
                   "reason": reason, "sources": sources or {},
                   "context": None if reason else context_from_sources(sources, observed_at_ms)}
        _validate_payload(payload)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > 8192:
            raise ValueError("context record byte limit reached")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT observed_at_ms,sha256 FROM historical_context_records WHERE symbol=? ORDER BY observed_at_ms DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            if latest and observed_at_ms <= latest[0]:
                raise ValueError("context clock did not advance")
            count = connection.execute("SELECT COUNT(*) FROM historical_context_records").fetchone()[0]
            pages = connection.execute("PRAGMA page_count").fetchone()[0]
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            if count >= self.maximum_records or (pages + 8) * page_size > self.maximum_bytes:
                raise RuntimeError("context storage capacity reached")
            previous = latest[1] if latest else ""
            digest = fingerprint({"payload": payload, "previous_sha256": previous})
            connection.execute(
                "INSERT INTO historical_context_records(symbol,observed_at_ms,session_id,status,payload,sha256,previous_sha256) "
                "VALUES(?,?,?,?,?,?,?)", (symbol, observed_at_ms, session_id, payload["status"], encoded, digest, previous),
            )
            if connection.execute("PRAGMA page_count").fetchone()[0] * page_size > self.maximum_bytes:
                raise RuntimeError("context storage capacity reached")
        return {"status": payload["status"], "observed_at_ms": observed_at_ms, "sha256": digest, "reason": reason}


def export_context(path: Path, *, symbol: str, classifier_fingerprint: str,
                   start_ms: int, end_ms: int, cutoff_ms: int) -> dict:
    """Export one continuous, attested interval; reads never initialize a database."""
    symbol_name(symbol)
    if not stamp(start_ms) < stamp(end_ms) <= stamp(cutoff_ms):
        raise ValueError("context export window invalid")
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        if (connection.execute("PRAGMA user_version").fetchone()[0] != 1
                or connection.execute("SELECT sha256 FROM context_schema WHERE version=1").fetchone() != (digest,)):
            raise ValueError("context export schema differs")
        first = connection.execute(
            "SELECT observed_at_ms FROM historical_context_records WHERE symbol=? AND observed_at_ms<=? "
            "ORDER BY observed_at_ms DESC LIMIT 1", (symbol, start_ms),
        ).fetchone()
        if first is None:
            raise ValueError("past historical context unavailable")
        cursor = connection.execute(
            "SELECT observed_at_ms,session_id,status,payload,sha256,previous_sha256 FROM historical_context_records "
            "WHERE symbol=? AND observed_at_ms>=? AND observed_at_ms<=? ORDER BY observed_at_ms LIMIT ?",
            (symbol, first[0], end_ms, MAX_EXPORT_RECORDS + 1),
        )
        records, rows = [], []
        previous, session, covered, size = None, None, start_ms, 0
        for observed, row_session, status, raw, hashed, prior in cursor:
            size += len(raw.encode())
            if len(records) >= MAX_EXPORT_RECORDS or size > MAX_EXPORT_BYTES or len(raw.encode()) > 8192:
                raise ValueError("context export capacity reached")
            payload = json.loads(raw)
            _validate_payload(payload)
            if (hashed != fingerprint({"payload": payload, "previous_sha256": prior})
                    or previous is not None and prior != previous
                    or session is not None and session != row_session
                    or (observed, row_session, status, symbol) != (payload["observed_at_ms"], payload["session_id"], payload["status"], payload["symbol"])):
                raise ValueError("context chain or session differs")
            if status != "AVAILABLE":
                raise ValueError("context interval contains unavailable evidence")
            row = payload["context"]
            if row["classifier_fingerprint"] != classifier_fingerprint or observed > covered:
                raise ValueError("context classifier differs or interval has a gap")
            covered = row["valid_until_ms"]
            previous, session = hashed, row_session
            records.append({"payload": payload, "sha256": hashed, "previous_sha256": prior})
            rows.append(row)
        if not rows or covered <= end_ms:
            raise ValueError("context does not cover the terminal observation tail")
        body = {"schema_version": 1, "mode": "SHADOW", "apply_allowed": False,
                "context": rows, "records": records, "symbol": symbol, "start_ms": start_ms,
                "end_ms": end_ms, "cutoff_ms": cutoff_ms, "session_id": session}
        result = dict(body, sha256=fingerprint(body))
        if len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()) > MAX_EXPORT_BYTES:
            raise ValueError("context export capacity reached")
        return result
    finally:
        connection.close()


def continuous_context_intervals(
    path: Path,
    *,
    symbol: str,
    classifier_fingerprint: str,
    start_ms: int,
    end_ms: int,
    cutoff_ms: int,
) -> list[dict[str, object]]:
    """Return bounded continuous AVAILABLE spans without joining a context gap."""
    symbol_name(symbol)
    if not stamp(start_ms) < stamp(end_ms) <= stamp(cutoff_ms):
        raise ValueError("context interval window invalid")
    connection = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        if (
            connection.execute("PRAGMA user_version").fetchone()[0] != 1
            or connection.execute(
                "SELECT sha256 FROM context_schema WHERE version=1"
            ).fetchone()
            != (digest,)
        ):
            raise ValueError("context interval schema differs")
        first = connection.execute(
            "SELECT observed_at_ms FROM historical_context_records "
            "WHERE symbol=? AND observed_at_ms<=? "
            "ORDER BY observed_at_ms DESC LIMIT 1",
            (symbol, start_ms),
        ).fetchone()
        if first is None:
            return []
        cursor = connection.execute(
            "SELECT observed_at_ms,session_id,status,payload,sha256,previous_sha256 "
            "FROM historical_context_records WHERE symbol=? "
            "AND observed_at_ms>=? AND observed_at_ms<=? "
            "ORDER BY observed_at_ms LIMIT ?",
            (symbol, first[0], end_ms, MAX_EXPORT_RECORDS + 1),
        )
        intervals: list[dict[str, object]] = []
        current: dict[str, object] | None = None
        previous: str | None = None
        size = count = 0
        for observed, row_session, status, raw, hashed, prior in cursor:
            encoded_size = len(raw.encode())
            size += encoded_size
            count += 1
            if (
                count > MAX_EXPORT_RECORDS
                or size > MAX_EXPORT_BYTES
                or encoded_size > 8192
            ):
                raise ValueError("context interval capacity reached")
            payload = json.loads(raw)
            _validate_payload(payload)
            if (
                hashed
                != fingerprint({"payload": payload, "previous_sha256": prior})
                or previous is not None
                and prior != previous
                or (observed, row_session, status, symbol)
                != (
                    payload["observed_at_ms"],
                    payload["session_id"],
                    payload["status"],
                    payload["symbol"],
                )
            ):
                raise ValueError("context interval chain differs")
            previous = hashed
            row = payload["context"] if status == "AVAILABLE" else None
            identity = (
                row_session,
                row.get("classifier_fingerprint") if row else None,
                row.get("panic_source_fingerprint") if row else None,
            )
            can_extend = bool(
                current is not None
                and row is not None
                and identity
                == (
                    current["session_id"],
                    current["classifier_fingerprint"],
                    current["panic_source_fingerprint"],
                )
                and observed <= int(current["end_ms"])
            )
            if not can_extend and current is not None:
                current["end_ms"] = min(int(current["end_ms"]), observed)
                if int(current["start_ms"]) < int(current["end_ms"]):
                    intervals.append(current)
                current = None
            if (
                row is None
                or row.get("classifier_fingerprint")
                != classifier_fingerprint
            ):
                continue
            if current is None:
                current = {
                    "start_ms": max(start_ms, observed),
                    "end_ms": int(row["valid_until_ms"]),
                    "session_id": row_session,
                    "classifier_fingerprint": classifier_fingerprint,
                    "panic_source_fingerprint": str(
                        row["panic_source_fingerprint"]
                    ),
                }
            else:
                current["end_ms"] = max(
                    int(current["end_ms"]), int(row["valid_until_ms"])
                )
        if current is not None and int(current["start_ms"]) < int(
            current["end_ms"]
        ):
            intervals.append(current)
        return intervals
    finally:
        connection.close()
