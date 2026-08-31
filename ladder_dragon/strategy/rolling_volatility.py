# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: publish bounded rolling volatility from a verified public book.
"""Disposable rolling volatility telemetry for the fail-closed BUY guard."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Deque

from ladder_dragon.strategy.depth_segments import PublicBook, atomic_json
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.volatility_policy import (
    VOLATILITY_MEASUREMENT_WINDOW_MS,
    VOLATILITY_METRIC,
    VOLATILITY_PUBLISH_INTERVAL_MS,
)


ROLLING_VOLATILITY_FILENAME = ".rolling-volatility-SOLUSDT.json"
ROLLING_WINDOW_MS = VOLATILITY_MEASUREMENT_WINDOW_MS
ROLLING_PUBLISH_INTERVAL_MS = VOLATILITY_PUBLISH_INTERVAL_MS
MINIMUM_BOOK_UPDATES = 100


class RollingVolatilityPublisher:
    """Overwrite one derived public record after each complete rolling window."""

    def __init__(self, path: Path, *, symbol: str, session_id: str) -> None:
        self.path = path
        self.symbol = symbol
        self.session_id = session_id
        self._mids: Deque[tuple[int, Decimal]] = deque()
        self._last_published_ms = 0

    def observe(self, book: PublicBook) -> dict[str, object] | None:
        """Observe one sequence-verified book and publish at five-minute cadence."""
        if book.update_id is None or not book.bids or not book.asks:
            raise ValueError("rolling volatility book is unavailable")
        observed_at_ms = int(book.received_ms)
        bid = max(book.bids)
        ask = min(book.asks)
        if observed_at_ms <= 0 or bid <= 0 or ask <= bid:
            raise ValueError("rolling volatility book is invalid")
        self._mids.append((observed_at_ms, (bid + ask) / Decimal("2")))
        cutoff = observed_at_ms - ROLLING_WINDOW_MS
        while len(self._mids) > 1 and self._mids[1][0] < cutoff:
            self._mids.popleft()
        if (
            len(self._mids) < MINIMUM_BOOK_UPDATES + 1
            or self._mids[-1][0] - self._mids[0][0] < ROLLING_WINDOW_MS
            or observed_at_ms - self._last_published_ms
            < ROLLING_PUBLISH_INTERVAL_MS
        ):
            return None
        points = tuple(self._mids)
        moves = sorted(
            abs(current / previous - Decimal("1")) * Decimal("10000")
            for (_previous_ts, previous), (current_ts, current)
            in zip(points, points[1:])
            if previous > 0 and current_ts >= cutoff
        )
        if len(moves) < MINIMUM_BOOK_UPDATES:
            return None
        quantile_index = (len(moves) - 1) * 95 // 100
        body: dict[str, object] = {
            "schema_version": 2,
            "mode": "PUBLIC_READ_ONLY",
            "apply_allowed": False,
            "contains_secrets": False,
            "symbol": self.symbol,
            "session_id": self.session_id,
            "source": "binance-public-websocket",
            "sequence_verified": True,
            "volatility_metric": VOLATILITY_METRIC,
            "measurement_window_ms": ROLLING_WINDOW_MS,
            "publish_interval_ms": ROLLING_PUBLISH_INTERVAL_MS,
            "window_started_at_ms": cutoff,
            "window_ended_at_ms": observed_at_ms,
            "updated_at_ms": observed_at_ms,
            "book_update_count": len(moves) + 1,
            "last_update_id": int(book.update_id),
            "volatility_bps_p95": format(moves[quantile_index], "f"),
        }
        payload = {**body, "telemetry_sha256": fingerprint(body)}
        atomic_json(self.path, payload, replace=True)
        self._last_published_ms = observed_at_ms
        return payload


__all__ = [
    "ROLLING_VOLATILITY_FILENAME",
    "RollingVolatilityPublisher",
]
