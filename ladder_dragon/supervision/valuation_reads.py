# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound parallel valuation routes across all account assets.
"""Snapshot-owned public I/O capacity; no persistent observations or authority."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from ladder_dragon.risk.asset_policy import STABLE_VALUATION_ASSETS
from ladder_dragon.execution.read_timing import record_read


class ValuationReads:
    """Share network capacity across asset workers and route workers."""

    def __init__(self, concurrency: int):
        self._concurrency = concurrency
        self._capacity = threading.BoundedSemaphore(concurrency)
        # Separate route workers avoid submitting nested work to asset workers.
        self._routes = ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="risk-route")

    def read(self, reader, *args, **kwargs):
        """Acquire capacity only around actual public I/O, never nested work."""
        started = time.monotonic()
        with self._capacity:
            record_read("pool_wait_ms", max(0, round((time.monotonic() - started) * 1000)))
            return reader(*args, **kwargs)

    def routes(self, quotes, reader):
        """Resolve in policy order, regardless of response completion order."""
        pending = list(quotes)
        # Resolve cheap stable routes before starting speculative bridge reads.
        while pending and (self._concurrency == 1 or pending[0] in STABLE_VALUATION_ASSETS):
            yield reader(pending.pop(0))
        futures = [self._routes.submit(reader, quote) for quote in pending]
        for future in futures:
            yield future.result()

    def close(self):
        """Drain all reads before any snapshot publication or failure report."""
        self._routes.shutdown(wait=True)
