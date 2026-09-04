# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: retain bounded, disposable context failures outside immutable evidence.
"""Single-collector diagnostics; never an input to selection or execution."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import stat

import requests

MAX_BYTES = 32_768
MAX_EVENTS = 64
RETENTION_MS = 7 * 24 * 60 * 60_000
STAGES = frozenset({"PANIC_WARMUP", "PANIC_REFRESH", "PANIC_MATCH", "RUNTIME_SOURCE",
                    "FILTER_SOURCE", "FEE_SOURCE", "SOURCE_BUNDLE", "PERSISTENCE", "CAPTURE"})
CATEGORIES = frozenset({"TIMEOUT", "NETWORK", "COOLDOWN", "HTTP_RATE_LIMIT", "HTTP_AUTH",
                        "HTTP_SERVER", "HTTP_OTHER", "RESPONSE_LIMIT", "INVALID_SOURCE",
                        "STATE_MISMATCH", "PERSISTENCE", "BLOCKED", "OTHER"})


class ContextSourceError(RuntimeError):
    """Carry only a fixed category across the source transport boundary."""

    def __init__(self, category: str):
        self.category = category if category in CATEGORIES else "OTHER"
        message = ("context source HTTP failure" if self.category.startswith("HTTP_") else
                   "context source cooldown active" if self.category == "COOLDOWN" else
                   "context source network failure")
        super().__init__(message)


class ContextResponseLimitError(ValueError):
    """Preserve the existing validation error boundary for response limits."""

    def __init__(self):
        super().__init__("context source response limit reached")


def error_category(exc: BaseException, stage: str) -> str:
    if isinstance(exc, ContextResponseLimitError):
        return "RESPONSE_LIMIT"
    if isinstance(exc, ContextSourceError):
        return exc.category if exc.category in CATEGORIES else "OTHER"
    if stage == "PERSISTENCE" or isinstance(exc, sqlite3.Error):
        return "PERSISTENCE"
    if isinstance(exc, requests.Timeout):
        return "TIMEOUT"
    if isinstance(exc, requests.RequestException):
        return "NETWORK"
    if stage == "PANIC_MATCH":
        return "STATE_MISMATCH"
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError, ArithmeticError)):
        return "INVALID_SOURCE"
    return "OTHER"


class ContextDiagnostics:
    """Retain at most 64 failures for seven days; counters cover retained events."""

    def __init__(self, path: Path):
        self.path = path

    def update(self, events: list[dict], now_ms: int) -> dict:
        # Reject damaged telemetry, rather than repairing it into apparent proof.
        if type(now_ms) is not int or now_ms <= 0 or not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError("diagnostic input invalid")
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            with os.fdopen(os.open(self.path, flags), "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError("diagnostic file must be regular")
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("diagnostic capacity exceeded")
            stored = json.loads(raw)
        except FileNotFoundError:
            stored = {"schema_version": 1, "events": []}
        if (not isinstance(stored, dict) or set(stored) != {"schema_version", "events"}
                or type(stored["schema_version"]) is not int or stored["schema_version"] != 1
                or not isinstance(stored["events"], list) or len(stored["events"]) > MAX_EVENTS):
            raise ValueError("diagnostic schema invalid")
        combined = stored["events"] + events
        for event in combined:
            if (not isinstance(event, dict) or set(event) != {"observed_at_ms", "stage", "category"}
                    or type(event["observed_at_ms"]) is not int
                    or not 0 < event["observed_at_ms"] <= now_ms
                    or not isinstance(event["stage"], str) or event["stage"] not in STAGES
                    or not isinstance(event["category"], str) or event["category"] not in CATEGORIES):
                raise ValueError("diagnostic event invalid")
        retained = [e for e in combined if now_ms - e["observed_at_ms"] < RETENTION_MS][-MAX_EVENTS:]
        if retained != stored["events"]:
            body = json.dumps({"schema_version": 1, "events": retained}, sort_keys=True).encode()
            if len(body) > MAX_BYTES:
                raise ValueError("diagnostic capacity exceeded")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
            descriptor = os.open(temporary, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    metadata = os.fstat(handle.fileno())
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise ValueError("diagnostic temporary file must be private and regular")
                    os.ftruncate(handle.fileno(), 0)
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return {"status": "AVAILABLE", "retained_failure_count": len(retained),
                "last_failure": dict(retained[-1]) if retained else None,
                "stage_counts": dict(Counter(e["stage"] for e in retained)),
                "category_counts": dict(Counter(e["category"] for e in retained))}
