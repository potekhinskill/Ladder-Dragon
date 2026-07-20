# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: persist sanitized order-latency samples for replay calibration.
"""Sanitized correlation between durable order intent and executionReport."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from ladder_dragon.execution.user_stream import OrderStreamSignal


def append_execution_latency_sample(
    path: str | Path,
    signal: OrderStreamSignal,
    *,
    intent_created_at_ms: int,
) -> dict[str, object]:
    """Append one non-secret timing sample with a hashed client identity."""
    created = int(intent_created_at_ms)
    received = int(signal.received_time_ms)
    if created <= 0 or received < created:
        raise ValueError("execution latency timestamps are invalid")
    payload: dict[str, object] = {
        "schema_version": 1,
        "symbol": signal.symbol,
        "order_ref": hashlib.sha256(
            f"{signal.symbol}:{signal.order_id}:{signal.client_order_id}".encode()
        ).hexdigest()[:24],
        "intent_created_at_ms": created,
        "event_time_ms": int(signal.event_time_ms),
        "transaction_time_ms": int(signal.transaction_time_ms),
        "received_at_ms": received,
        "execution_type": signal.execution_type,
        "order_status": signal.order_status,
        "intent_to_event_ms": max(0, int(signal.event_time_ms) - created),
        "intent_to_receive_ms": received - created,
        "exchange_to_receive_ms": (
            max(0, received - int(signal.event_time_ms))
            if signal.event_time_ms > 0 else None
        ),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(
        target,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, line.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return payload


def load_execution_latencies(path: str | Path) -> list[int]:
    """Load local pre-POST-to-NEW-report latency from sanitized JSONL."""
    values: list[int] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise ValueError(f"latency line {line_number} is not an object")
            if int(payload.get("schema_version", 0)) != 1:
                raise ValueError(f"latency line {line_number} has unsupported schema")
            if (
                str(payload.get("execution_type", "")).upper() != "NEW"
                or str(payload.get("order_status", "")).upper() != "NEW"
            ):
                continue
            value = int(payload.get("intent_to_receive_ms", -1))
            if value < 0 or value > 300_000:
                raise ValueError(f"latency line {line_number} is out of range")
            values.append(value)
    return values
