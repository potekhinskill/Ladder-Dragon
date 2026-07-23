# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: record sanitized monotonic phases of the low-latency execution path.
"""Bounded, non-secret latency tracing for trading decisions and order ACKs."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


ALLOWED_PHASES = frozenset(
    {
        "market_event_received",
        "feature_start",
        "feature_end",
        "risk_decision",
        "journal_commit",
        "request_sent",
        "exchange_ack",
        "fill_received",
        "protection_active",
        "cancel_replace_ack",
    }
)


@dataclass
class LatencyTrace:
    """Capture phase offsets without persisting order IDs or credentials."""

    symbol: str
    operation: str
    monotonic_ns: Callable[[], int] = time.monotonic_ns
    wall_time_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    _started_ns: int = field(init=False)
    _started_at_ms: int = field(init=False)
    _phases: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()[:20]
        self.operation = self.operation.strip().upper()[:32]
        self._started_ns = int(self.monotonic_ns())
        self._started_at_ms = int(self.wall_time_ms())

    def mark(self, phase: str) -> int:
        normalized = str(phase).strip().lower()
        if normalized not in ALLOWED_PHASES:
            raise ValueError(f"unsupported latency phase: {normalized}")
        elapsed_ns = max(0, int(self.monotonic_ns()) - self._started_ns)
        elapsed_us = elapsed_ns // 1_000
        self._phases[normalized] = elapsed_us
        return elapsed_us

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "trace_id": self.trace_id,
            "symbol": self.symbol,
            "operation": self.operation,
            "started_at_ms": self._started_at_ms,
            "phases_us": dict(sorted(self._phases.items())),
        }

    def append(self, path: str | Path) -> dict[str, object]:
        payload = self.payload()
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
        finally:
            os.close(descriptor)
        return payload
