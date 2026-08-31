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
    VOLATILITY_EVENT_POPULATION,
    VOLATILITY_MEASUREMENT_WINDOW_MS,
    VOLATILITY_METRIC,
    VOLATILITY_PUBLISH_INTERVAL_MS,
)
from ladder_dragon.strategy.volatility_measurement import observe_depth_mid


ROLLING_VOLATILITY_FILENAME = ".rolling-volatility-SOLUSDT.json"
CURRENT_DEPTH_SESSION_FILENAME = ".current-depth-session-SOLUSDT.json"
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
        self._last_session_published_ms = 0
        self._previous_mid: Decimal | None = None
        self._session_path = path.parent / CURRENT_DEPTH_SESSION_FILENAME
        self._publish_session(status="SYNCHRONIZING", updated_at_ms=0)

    def _publish_session(
        self, *, status: str, updated_at_ms: int, last_update_id: int = 0
    ) -> None:
        body: dict[str, object] = {
            "schema_version": 1,
            "mode": "PUBLIC_READ_ONLY",
            "apply_allowed": False,
            "contains_secrets": False,
            "symbol": self.symbol,
            "session_id": self.session_id,
            "status": status,
            "sequence_verified": status in {"WARMING", "READY"},
            "updated_at_ms": updated_at_ms,
            "last_update_id": last_update_id,
        }
        atomic_json(
            self._session_path,
            {**body, "session_sha256": fingerprint(body)},
            replace=True,
        )

    def observe(self, book: PublicBook) -> dict[str, object] | None:
        """Observe one sequence-verified book and publish at five-minute cadence."""
        if book.update_id is None or not book.bids or not book.asks:
            raise ValueError("rolling volatility book is unavailable")
        observed_at_ms = int(book.received_ms)
        bid = max(book.bids)
        ask = min(book.asks)
        if observed_at_ms <= 0 or bid <= 0 or ask <= bid:
            raise ValueError("rolling volatility book is invalid")
        self._previous_mid, _move = observe_depth_mid(
            event_type="depthUpdate", bid=bid, ask=ask,
            previous_mid=self._previous_mid,
        )
        if self._previous_mid is None:
            raise ValueError("rolling volatility mid is unavailable")
        self._mids.append((observed_at_ms, self._previous_mid))
        cutoff = observed_at_ms - ROLLING_WINDOW_MS
        while len(self._mids) > 1 and self._mids[1][0] < cutoff:
            self._mids.popleft()
        if (
            len(self._mids) < MINIMUM_BOOK_UPDATES + 1
            or self._mids[-1][0] - self._mids[0][0] < ROLLING_WINDOW_MS
            or observed_at_ms - self._last_published_ms
            < ROLLING_PUBLISH_INTERVAL_MS
        ):
            if (
                observed_at_ms - self._last_session_published_ms
                >= ROLLING_PUBLISH_INTERVAL_MS
            ):
                self._publish_session(
                    status="WARMING",
                    updated_at_ms=observed_at_ms,
                    last_update_id=int(book.update_id),
                )
                self._last_session_published_ms = observed_at_ms
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
            "volatility_event_population": VOLATILITY_EVENT_POPULATION,
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
        self._publish_session(
            status="READY",
            updated_at_ms=observed_at_ms,
            last_update_id=int(book.update_id),
        )
        self._last_published_ms = observed_at_ms
        self._last_session_published_ms = observed_at_ms
        return payload


__all__ = [
    "ROLLING_VOLATILITY_FILENAME",
    "CURRENT_DEPTH_SESSION_FILENAME",
    "RollingVolatilityPublisher",
]
