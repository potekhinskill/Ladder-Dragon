# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: record auditable public Binance Spot depth/trade archives.
"""Public-only Spot depth recorder used by offline replay calibration."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable, Optional

import requests
from websocket import WebSocketException, WebSocketTimeoutException, create_connection


REST_BASE = "https://data-api.binance.vision"
STREAM_BASE = "wss://stream.binance.com:9443/stream"


def _symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol or len(symbol) > 20 or not symbol.isalnum():
        raise ValueError("symbol must contain 1-20 letters or digits")
    return symbol


def stream_url(symbol: str) -> str:
    lower = _symbol(symbol).lower()
    return (
        f"{STREAM_BASE}?streams={lower}@depth@100ms/{lower}@aggTrade"
    )


def record_public_depth(
    symbol: str,
    output: str | Path,
    *,
    duration_sec: int = 300,
    max_events: int = 100_000,
    depth_limit: int = 1000,
    session: Optional[requests.Session] = None,
    connect: Optional[Callable[..., object]] = None,
    clock_ms: Optional[Callable[[], int]] = None,
) -> dict[str, object]:
    """Record snapshot plus contiguous public events and publish atomically."""
    symbol = _symbol(symbol)
    if duration_sec < 1 or max_events < 1:
        raise ValueError("duration and max_events must be positive")
    if depth_limit not in {100, 500, 1000, 5000}:
        raise ValueError("depth_limit must be 100, 500, 1000 or 5000")
    http = session or requests.Session()
    connector = connect or create_connection
    now_ms = clock_ms or (lambda: int(time.time() * 1000))
    target = Path(output)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    metadata_path = target.with_suffix(target.suffix + ".metadata.json")
    metadata_temporary = metadata_path.with_name(
        f".{metadata_path.name}.{os.getpid()}.tmp"
    )
    connection = connector(stream_url(symbol), timeout=10)
    started_ms = now_ms()
    written = 0
    depth_events = 0
    trade_events = 0
    last_update_id: Optional[int] = None
    deadline = time.monotonic() + duration_sec
    digest = hashlib.sha256()

    def emit(handle, payload: dict) -> None:
        nonlocal written
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        handle.write(encoded)
        digest.update(encoded)
        written += 1

    try:
        response = http.get(
            f"{REST_BASE}/api/v3/depth",
            params={"symbol": symbol, "limit": depth_limit},
            timeout=15,
        )
        response.raise_for_status()
        snapshot = response.json()
        if not isinstance(snapshot, dict) or "lastUpdateId" not in snapshot:
            raise ValueError("Binance depth snapshot is invalid")
        last_update_id = int(snapshot["lastUpdateId"])
        snapshot = {
            "lastUpdateId": last_update_id,
            "E": now_ms(),
            "s": symbol,
            "bids": snapshot.get("bids", []),
            "asks": snapshot.get("asks", []),
            "_received_at_ms": now_ms(),
            "_source": "binance-public-rest-depth",
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("wb") as handle:
            emit(handle, snapshot)
            synchronized = False
            while written < max_events and time.monotonic() < deadline:
                try:
                    raw = connection.recv()
                except WebSocketTimeoutException:
                    connection.ping()
                    continue
                envelope = json.loads(raw)
                row = envelope.get("data", envelope)
                if not isinstance(row, dict):
                    continue
                event_type = str(row.get("e", ""))
                row = dict(row)
                row["_received_at_ms"] = now_ms()
                row["_source"] = "binance-public-websocket"
                if event_type == "depthUpdate":
                    first_id = int(row.get("U", 0))
                    final_id = int(row.get("u", 0))
                    if final_id <= last_update_id:
                        continue
                    if not synchronized:
                        if not first_id <= last_update_id + 1 <= final_id:
                            continue
                        synchronized = True
                    elif first_id != last_update_id + 1:
                        raise ValueError(
                            "Binance depth sequence gap while recording: "
                            f"last={last_update_id} U={first_id} u={final_id}"
                        )
                    last_update_id = final_id
                    depth_events += 1
                    emit(handle, row)
                elif event_type == "aggTrade" and synchronized:
                    trade_events += 1
                    emit(handle, row)
            handle.flush()
            os.fsync(handle.fileno())
        if depth_events == 0:
            raise ValueError("no contiguous depth events were recorded")
        metadata = {
            "schema_version": 1,
            "symbol": symbol,
            "started_at_ms": started_ms,
            "finished_at_ms": now_ms(),
            "event_count": written,
            "depth_event_count": depth_events,
            "trade_event_count": trade_events,
            "first_snapshot_update_id": int(snapshot["lastUpdateId"]),
            "last_update_id": last_update_id,
            "archive_sha256": digest.hexdigest(),
            "rest_source": REST_BASE,
            "stream_source": STREAM_BASE,
            "contains_secrets": False,
        }
        encoded_metadata = (
            json.dumps(metadata, indent=2, sort_keys=True) + "\n"
        ).encode()
        with metadata_temporary.open("wb") as handle:
            handle.write(encoded_metadata)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.replace(metadata_temporary, metadata_path)
        return metadata
    finally:
        try:
            connection.close()
        except (OSError, RuntimeError, WebSocketException):
            pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            metadata_temporary.unlink(missing_ok=True)
        except OSError:
            pass
