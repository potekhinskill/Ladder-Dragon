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


MAXIMUM_ARCHIVE_SESSIONS = 32
MAXIMUM_ARCHIVE_BYTES = 512 * 1024 * 1024


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
        tail_sec: float = 2.0,
        recorder: Callable[..., dict[str, object]] = record_public_depth,
    ) -> None:
        if maximum_duration_sec < 30 or maximum_duration_sec > 3600:
            raise ValueError("validation archive duration is out of range")
        if maximum_events < 1000 or maximum_events > 1_000_000:
            raise ValueError("validation archive event limit is out of range")
        if ready_timeout_sec < 1 or ready_timeout_sec > 60:
            raise ValueError("validation archive readiness timeout is invalid")
        if tail_sec < 0 or tail_sec > 10:
            raise ValueError("validation archive tail is invalid")
        self.symbol = symbol.strip().upper()
        self.directory = Path(directory)
        self.label = label.strip().lower()
        self.maximum_duration_sec = maximum_duration_sec
        self.maximum_events = maximum_events
        self.ready_timeout_sec = ready_timeout_sec
        self.tail_sec = tail_sec
        self.recorder = recorder
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._metadata: dict[str, object] | None = None
        self.path: Path | None = None

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
                ready_callback=self._ready.set,
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
        if self._thread is not None:
            raise RuntimeError("validation archive already started")
        self._check_capacity()
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.path = self.directory / (
            f"{self.symbol}-{self.label}-{stamp}-{time.time_ns()}.jsonl"
        )
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
        self._thread.join(timeout=5)
        if self._error is not None:
            raise RuntimeError(
                "validation depth archive failed before readiness"
            ) from self._error
        raise RuntimeError("validation depth archive did not become ready")

    def stop(self) -> dict[str, object]:
        """Publish the archive only after the terminal mutation boundary."""
        if self._thread is None or self.path is None:
            raise RuntimeError("validation archive is not running")
        if self.tail_sec:
            time.sleep(self.tail_sec)
        self._stop.set()
        self._thread.join(timeout=30)
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
        return dict(metadata)


__all__ = ["ContinuousDepthArchive"]
