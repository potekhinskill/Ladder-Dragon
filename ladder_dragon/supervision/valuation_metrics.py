# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: measure valuation routes without retaining financial observations.
"""Fixed-size, snapshot-owned counters for logical public reads."""

import threading
import time

import requests


ROUTES = ("direct", "cross_usdc", "cross_fdusd", "cross_btc", "cross_eth", "bridge", "depth", "batch")
COUNTERS = ("reads", "read_ms", "cache_hits", "negative_hits", "missing", "transient", "other_errors")


class ValuationMetrics:
    """Retain counts and elapsed time only; never retain arguments or errors."""

    def __init__(self):
        self._lock = threading.Lock()
        self._values = {f"{route}_{counter}": 0 for route in ROUTES for counter in COUNTERS}

    def increment(self, route, counter, amount=1):
        key = f"{route}_{counter}"
        with self._lock:
            self._values[key] += amount

    def read(self, route, reader, *args, **kwargs):
        started = time.monotonic()
        self.increment(route, "reads")
        try:
            return reader(*args, **kwargs)
        except (ArithmeticError, KeyError, RuntimeError, TypeError, ValueError, requests.RequestException) as error:
            code = getattr(error, "code", None)
            status = getattr(error, "status", None)
            if code == -1121:
                category = "missing"
            elif (isinstance(error, requests.RequestException)
                  or status in (418, 429)
                  or (isinstance(status, int) and status >= 500)
                  or code in (-1021, -1000, -1001, -1003)):
                category = "transient"
            else:
                category = "other_errors"
            self.increment(route, category)
            raise
        finally:
            self.increment(route, "read_ms", max(0, round((time.monotonic() - started) * 1000)))

    def snapshot(self, *, failed):
        with self._lock:
            return {"attempt_failed": int(failed), **self._values}
