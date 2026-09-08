# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose fixed numeric read diagnostics without request identity.
"""Thread-local, disposable telemetry; no URLs, payloads, or persistent data."""

from contextlib import contextmanager
from contextvars import ContextVar
import time

COUNTERS = ("http_attempts", "headers_ms", "body_ms", "retry_wait_ms", "pool_wait_ms",
            "http_4xx", "http_5xx", "transport_errors", "read_cpu_ms",
            "close_ms", "close_cpu_ms", "json_decode_ms", "json_decode_cpu_ms",
            "batch_validate_ms", "batch_validate_cpu_ms")
_sink = ContextVar("public_read_timing", default=None)


@contextmanager
def observe_reads(sink):
    """Restore the prior observer even when a read fails."""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def record_read(counter, amount=1):
    """Accept only fixed counter names and nonnegative integer values."""
    sink = _sink.get()
    if sink is not None and counter in COUNTERS and type(amount) is int and amount >= 0:
        sink(counter, amount)


def measured_read(stage, reader, *args, **kwargs):
    """Separate wall time from thread CPU without retaining request data."""
    started, cpu_started = time.monotonic(), time.thread_time()
    try:
        return reader(*args, **kwargs)
    finally:
        record_read(stage + "_ms", max(0, round((time.monotonic() - started) * 1000)))
        record_read(stage + "_cpu_ms", max(0, round((time.thread_time() - cpu_started) * 1000)))
