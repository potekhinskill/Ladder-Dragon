# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep slow read-only snapshots outside dashboard request deadlines.
"""Provide a bounded stale-while-refresh cache for read-only dashboard data."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any


class StaleWhileRefreshCache:
    """Return usable cached data while one background refresh runs."""

    def __init__(
        self,
        *,
        ttl_sec: float,
        maximum_stale_sec: float,
        load_errors: tuple[type[BaseException], ...],
        error_logger: Callable[[BaseException], None],
        clock: Callable[[], float] = time.monotonic,
        maximum_entries: int = 16,
    ) -> None:
        if ttl_sec <= 0 or maximum_stale_sec < ttl_sec or maximum_entries < 1:
            raise ValueError("invalid stale refresh cache duration")
        self._ttl_sec = float(ttl_sec)
        self._maximum_stale_sec = float(maximum_stale_sec)
        self._load_errors = load_errors
        self._error_logger = error_logger
        self._clock = clock
        self._maximum_entries = int(maximum_entries)
        self._entries: dict[Hashable, dict[str, Any]] = {}
        self._active = False
        self._lock = threading.Lock()

    def _refresh(
        self,
        key: Hashable,
        loader: Callable[[], dict[str, object]],
    ) -> None:
        try:
            payload = loader()
            if not isinstance(payload, dict):
                raise TypeError("snapshot loader must return an object")
            with self._lock:
                if key not in self._entries and len(self._entries) >= self._maximum_entries:
                    oldest = min(
                        self._entries,
                        key=lambda entry_key: float(self._entries[entry_key].get("ts", 0.0)),
                    )
                    self._entries.pop(oldest, None)
                self._entries[key] = {
                    "ts": self._clock(),
                    "payload": dict(payload),
                }
        except self._load_errors as exc:
            self._error_logger(exc)
        finally:
            with self._lock:
                self._active = False

    def get(
        self,
        key: Hashable,
        loader: Callable[[], dict[str, object]],
    ) -> tuple[dict[str, object] | None, str, float | None]:
        """Return data immediately and start at most one refresh process."""
        now = self._clock()
        payload: dict[str, object] | None = None
        age: float | None = None
        start_refresh = False
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and isinstance(entry.get("payload"), dict):
                age = max(0.0, now - float(entry.get("ts", 0.0)))
                if age <= self._maximum_stale_sec:
                    payload = dict(entry["payload"])
            if (
                (payload is None or age is None or age >= self._ttl_sec)
                and not self._active
            ):
                self._active = True
                start_refresh = True
            refreshing = self._active

        if start_refresh:
            threading.Thread(
                target=self._refresh,
                args=(key, loader),
                name="dashboard-stale-refresh",
                daemon=True,
            ).start()

        if payload is None or age is None:
            return None, "refreshing" if refreshing else "unavailable", None
        return payload, "fresh" if age < self._ttl_sec else "stale", age
