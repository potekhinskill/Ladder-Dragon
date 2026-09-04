# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound parallel valuation routes across all account assets.
"""Snapshot-owned public I/O capacity; no persistent observations or authority."""

from concurrent.futures import ThreadPoolExecutor
import threading


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
        with self._capacity:
            return reader(*args, **kwargs)

    def routes(self, quotes, reader):
        """Resolve in policy order, regardless of response completion order."""
        if self._concurrency == 1:
            # Preserve the serial short-circuit path for the minimum setting.
            return map(reader, quotes)
        futures = [self._routes.submit(reader, quote) for quote in quotes]
        return [future.result() for future in futures]

    def close(self):
        """Drain all reads before any snapshot publication or failure report."""
        self._routes.shutdown(wait=True)
