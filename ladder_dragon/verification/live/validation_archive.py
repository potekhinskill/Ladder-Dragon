# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind one continuous public depth archive to a Mainnet validation mutation.
"""Continuous public replay evidence for bounded Mainnet validation drills."""

from __future__ import annotations

from pathlib import Path
import threading
import time
from typing import Callable

import requests
from websocket import WebSocketException

from ladder_dragon.strategy.depth_archive import record_public_depth
from ladder_dragon.strategy.replay_policy import (
    PRODUCTION_REPLAY_ACCEPTANCE_POLICY,
)


MAXIMUM_ARCHIVE_SESSIONS = 32
MAXIMUM_ARCHIVE_BYTES = 512 * 1024 * 1024


class ValidationArchiveReadinessError(RuntimeError):
    """Expose bounded, secret-safe public archive startup diagnostics."""

    def __init__(self, *, reason_code: str, attempts: int, cause_type: str) -> None:
        self.reason_code = reason_code
        self.attempts = attempts
        self.cause_type = cause_type
        super().__init__(
            "validation depth archive readiness failed: "
            f"code={reason_code} attempts={attempts} cause={cause_type}"
        )


class ValidationArchiveEvidenceError(RuntimeError):
    """Expose a stable error when a terminal archive is too short."""

    reason_code = "PUBLIC_ARCHIVE_EVIDENCE_INSUFFICIENT"
    attempts = 0
    cause_type = "EvidenceThreshold"

    def __init__(self) -> None:
        super().__init__(
            "validation depth archive evidence is insufficient: "
            f"code={self.reason_code} cause={self.cause_type}"
        )


class ContinuousDepthArchive:
    """Record one contiguous public session across an external mutation."""

    def __init__(
        self,
        *,
        symbol: str,
        directory: str | Path,
        label: str,
        maximum_duration_sec: int = 1800,
        maximum_events: int = 250_000,
        ready_timeout_sec: int = 30,
        readiness_attempts: int = 3,
        retry_delay_sec: float = 0.5,
        tail_sec: float = 2.0,
        evidence_timeout_sec: float = 120.0,
        minimum_depth_events: int = (
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.minimum_book_events
        ),
        minimum_trade_events: int = (
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.minimum_trades
        ),
        recorder: Callable[..., dict[str, object]] = record_public_depth,
    ) -> None:
        if maximum_duration_sec < 30 or maximum_duration_sec > 3600:
            raise ValueError("validation archive duration is out of range")
        if maximum_events < 1000 or maximum_events > 1_000_000:
            raise ValueError("validation archive event limit is out of range")
        if ready_timeout_sec < 1 or ready_timeout_sec > 60:
            raise ValueError("validation archive readiness timeout is invalid")
        if readiness_attempts < 1 or readiness_attempts > 3:
            raise ValueError("validation archive readiness attempts are invalid")
        if retry_delay_sec < 0 or retry_delay_sec > 5:
            raise ValueError("validation archive retry delay is invalid")
        if tail_sec < 0 or tail_sec > 10:
            raise ValueError("validation archive tail is invalid")
        if evidence_timeout_sec <= 0 or evidence_timeout_sec > 300:
            raise ValueError("validation archive evidence timeout is invalid")
        if (
            minimum_depth_events < 1
            or minimum_trade_events < 1
            or 1 + minimum_depth_events + minimum_trade_events > maximum_events
        ):
            raise ValueError("validation archive evidence minimum is invalid")
        self.symbol = symbol.strip().upper()
        self.directory = Path(directory)
        self.label = label.strip().lower()
        self.maximum_duration_sec = maximum_duration_sec
        self.maximum_events = maximum_events
        self.ready_timeout_sec = ready_timeout_sec
        self.readiness_attempts = readiness_attempts
        self.retry_delay_sec = retry_delay_sec
        self.tail_sec = tail_sec
        self.evidence_timeout_sec = evidence_timeout_sec
        self.minimum_depth_events = minimum_depth_events
        self.minimum_trade_events = minimum_trade_events
        self.recorder = recorder
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._force_stop = threading.Event()
        self._finished = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._metadata: dict[str, object] | None = None
        self.path: Path | None = None
        self._started = False

    def _check_capacity(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        archives = list(self.directory.glob("*.jsonl"))
        total_bytes = sum(path.stat().st_size for path in archives)
        if (
            len(archives) >= MAXIMUM_ARCHIVE_SESSIONS
            or total_bytes >= MAXIMUM_ARCHIVE_BYTES
        ):
            raise RuntimeError("validation archive capacity is reached")

    def _run(self) -> None:
        assert self.path is not None
        try:
            self._metadata = self.recorder(
                self.symbol,
                self.path,
                duration_sec=self.maximum_duration_sec,
                max_events=self.maximum_events,
                stop_requested=self._stop.is_set,
                force_stop_requested=self._force_stop.is_set,
                ready_callback=self._ready.set,
                minimum_depth_events_before_stop=self.minimum_depth_events,
                minimum_trade_events_before_stop=self.minimum_trade_events,
            )
        except (
            OSError,
            RuntimeError,
            ValueError,
            requests.RequestException,
            WebSocketException,
        ) as exc:
            self._error = exc
        finally:
            self._finished.set()

    def start(self) -> Path:
        """Start recording and wait for a contiguous depth handshake."""
        if self._started:
            raise RuntimeError("validation archive already started")
        self._started = True
        self._check_capacity()
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.path = self.directory / (
            f"{self.symbol}-{self.label}-{stamp}-{time.time_ns()}.jsonl"
        )
        for attempt in range(1, self.readiness_attempts + 1):
            if attempt > 1 and self.retry_delay_sec:
                time.sleep(self.retry_delay_sec * (2 ** (attempt - 2)))
            self._ready = threading.Event()
            self._stop = threading.Event()
            self._force_stop = threading.Event()
            self._finished = threading.Event()
            self._error = None
            self._metadata = None
            self._thread = threading.Thread(
                target=self._run,
                name="validation-depth-archive",
                daemon=True,
            )
            self._thread.start()
            deadline = time.monotonic() + self.ready_timeout_sec
            while time.monotonic() < deadline:
                if self._ready.wait(timeout=0.05):
                    return self.path
                if self._finished.is_set():
                    break
            self._stop.set()
            self._force_stop.set()
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise ValidationArchiveReadinessError(
                    reason_code="PUBLIC_ARCHIVE_STOP_TIMEOUT",
                    attempts=attempt,
                    cause_type="ThreadTimeout",
                )
            if attempt == self.readiness_attempts:
                cause_type = (
                    type(self._error).__name__
                    if self._error is not None else "ReadinessTimeout"
                )
                raise ValidationArchiveReadinessError(
                    reason_code=(
                        "PUBLIC_ARCHIVE_SOURCE_FAILED"
                        if self._error is not None
                        else "PUBLIC_ARCHIVE_NOT_READY"
                    ),
                    attempts=attempt,
                    cause_type=cause_type,
                ) from self._error
        raise AssertionError("validation archive readiness loop is unreachable")

    def stop(self) -> dict[str, object]:
        """Publish the archive only after the terminal mutation boundary."""
        if self._thread is None or self.path is None:
            raise RuntimeError("validation archive is not running")
        if self.tail_sec:
            time.sleep(self.tail_sec)
        self._stop.set()
        self._thread.join(timeout=self.evidence_timeout_sec)
        if self._thread.is_alive():
            self._force_stop.set()
            self._thread.join(timeout=15)
        if self._thread.is_alive():
            raise RuntimeError("validation depth archive did not stop")
        if self._error is not None:
            raise RuntimeError("validation depth archive failed") from self._error
        metadata = self._metadata
        if (
            not isinstance(metadata, dict)
            or metadata.get("contains_secrets") is not False
            or not self.path.is_file()
        ):
            raise RuntimeError("validation depth archive is incomplete")
        try:
            depth_events = int(metadata.get("depth_event_count", -1))
            trade_events = int(metadata.get("trade_event_count", -1))
        except (TypeError, ValueError) as exc:
            raise ValidationArchiveEvidenceError() from exc
        if (
            depth_events < self.minimum_depth_events
            or trade_events < self.minimum_trade_events
        ):
            raise ValidationArchiveEvidenceError()
        return dict(metadata)


__all__ = [
    "ContinuousDepthArchive",
    "ValidationArchiveEvidenceError",
    "ValidationArchiveReadinessError",
]
