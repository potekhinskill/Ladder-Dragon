# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: rotate public depth files without interrupting their WebSocket.
"""Continuous capture with bounded resources and explicit session boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from uuid import uuid4

import requests
from websocket import WebSocketException, WebSocketTimeoutException, create_connection

from ladder_dragon.strategy.depth_archive import REST_BASE, _symbol, stream_url
from ladder_dragon.strategy.depth_segments import (
    MAX_FRAME_BYTES, MAX_SEGMENTS, PublicBook, SegmentWriter,
)


class PublicStreamReconnect(RuntimeError):
    """Request a new public session after preserving complete prior events."""


def remaining_capacity(directory: Path, capacity_bytes: int) -> int:
    used = segments = files = 0
    for path in directory.iterdir():
        files += 1
        if files > MAX_SEGMENTS * 5:
            raise ValueError("public archive file inventory capacity reached")
        if path.is_file():
            used += path.stat().st_size
            segments += path.name.endswith(".jsonl.metadata.json")
    if segments >= MAX_SEGMENTS:
        raise ValueError("public archive segment capacity reached")
    return min(capacity_bytes - used, shutil.disk_usage(directory).free - MAX_FRAME_BYTES)


def public_snapshot(http, symbol: str) -> dict:
    """Enforce the decoded-byte ceiling before parsing an external response."""
    with http.get(f"{REST_BASE}/api/v3/depth", params={"symbol": symbol, "limit": 5000},
                  timeout=15, stream=True) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > MAX_FRAME_BYTES:
                raise ValueError("public depth response exceeds byte limit")
    snapshot = json.loads(body)
    if not isinstance(snapshot, dict):
        raise ValueError("public snapshot is not an object")
    return snapshot


def capture_segments(symbol: str, directory: Path, *, duration_sec: int = 3300,
                     max_events: int = 250_000, capacity_bytes: int = 8 * 1024**3,
                     stop_requested=lambda: False, connect=create_connection,
                     session=None, clock_ms=lambda: time.time_ns() // 1_000_000,
                     max_segments: int = 10_000) -> list[dict]:
    """Keep one stream and book across file rotation; never bridge reconnects."""
    symbol = _symbol(symbol)
    if not 1 <= duration_sec <= 3500 or not 2 <= max_events <= 1_000_000:
        raise ValueError("invalid public rotation limits")
    if not 1 <= max_segments <= 10_000 or capacity_bytes < MAX_FRAME_BYTES * 2:
        raise ValueError("invalid public capacity limits")
    directory.mkdir(parents=True, exist_ok=True)
    http = session or requests.Session()
    connection = connect(stream_url(symbol), timeout=10)
    book = PublicBook()
    writer = None
    completed: list[dict] = []
    session_id = uuid4().hex
    try:
        source = public_snapshot(http, symbol)
        book.apply({"s": symbol, "E": clock_ms(), "_received_at_ms": clock_ms(),
                    "lastUpdateId": source["lastUpdateId"],
                    "bids": source["bids"], "asks": source["asks"]})
        sync_deadline = time.monotonic() + 30
        synchronized = False
        while not stop_requested():
            if not synchronized and time.monotonic() > sync_deadline:
                raise ValueError("public depth synchronization timed out")
            try:
                raw = connection.recv()
            except WebSocketTimeoutException:
                connection.ping()
                continue
            except WebSocketException as exc:
                if writer is not None:
                    completed.append(writer.finish(book, "CONNECTION_INTERRUPTED"))
                    writer = None
                raise PublicStreamReconnect(
                    "public stream requires a new session"
                ) from exc
            if not raw:
                if writer is not None:
                    completed.append(writer.finish(book, "CONNECTION_CLOSED"))
                    writer = None
                raise PublicStreamReconnect("public stream closed")
            if len(raw.encode() if isinstance(raw, str) else raw) > MAX_FRAME_BYTES:
                raise ValueError("public stream frame missing or oversized")
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError("public stream envelope must be an object")
            row = envelope.get("data", envelope)
            if not isinstance(row, dict):
                raise ValueError("unexpected public stream payload")
            kind = row.get("e")
            if kind == "serverShutdown" or row.get("event") == "serverShutdown":
                # Binance closes each physical connection. Preserve the valid
                # prefix, then let systemd establish an independent session.
                if writer is not None:
                    completed.append(writer.finish(book, "SERVER_SHUTDOWN"))
                    writer = None
                raise PublicStreamReconnect("public stream server shutdown")
            if row.get("s") != symbol:
                raise ValueError("unexpected public stream symbol")
            fields = ({"e", "E", "s", "U", "u", "pu", "b", "a"}
                      if kind == "depthUpdate" else
                      {"e", "E", "s", "a", "p", "q", "f", "l", "T", "m"})
            if kind not in {"depthUpdate", "aggTrade"}:
                raise ValueError("unexpected public stream event")
            # Whitelisting prevents unrelated payload fields entering evidence.
            row = {key: value for key, value in row.items() if key in fields}
            row["_received_at_ms"] = clock_ms()
            row["_source"] = "binance-public-websocket"
            if not synchronized:
                if kind != "depthUpdate" or int(row["u"]) <= book.update_id:
                    continue
                book.apply(row)
                synchronized = True
                # The first verified book is the capture boundary. Earlier
                # buffered trades cannot be interpreted against a later book.
                continue
            if writer is not None and (
                writer.count >= max_events
                or row["_received_at_ms"] - writer.metadata["started_at_ms"] >= duration_sec * 1000
            ):
                completed.append(writer.finish(book, "ROTATION"))
                writer = None
                if len(completed) >= max_segments:
                    break
            if writer is None:
                remaining = remaining_capacity(directory, capacity_bytes)
                if remaining < MAX_FRAME_BYTES:
                    raise ValueError("public archive capacity requires verified archival")
                writer = SegmentWriter(directory, symbol, session_id, len(completed),
                                       completed[-1] if completed else None, book, remaining)
            # Validate before writing; invalid events never become committed evidence.
            book.apply(row)
            writer.emit(row)
        if writer is not None:
            completed.append(writer.finish(book, "STOP_REQUESTED"))
            writer = None
        return completed
    finally:
        # A failed session leaves only its unfinished temporary file. It cannot
        # be selected or joined to the next independently synchronized session.
        if writer is not None:
            writer.handle.close()
        connection.close()
        if session is None:
            http.close()
