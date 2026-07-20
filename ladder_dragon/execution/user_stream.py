# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: observe Binance Spot user events without replacing REST reconciliation.
"""Supplemental Binance Spot User Data Stream observer.

The stream is deliberately notification-only.  It never mutates orders,
balances, the order journal, or inventory.  Consumers use a signal to perform
the same authenticated REST query they would have performed on their normal
polling schedule.  REST therefore remains the source of truth after duplicate,
late, missing, or out-of-order WebSocket events.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from websocket import WebSocketException, WebSocketTimeoutException, create_connection


TERMINAL_EVENT_TYPES = {"eventStreamTerminated", "serverShutdown"}
ORDER_EVENT_TYPE = "executionReport"


@dataclass(frozen=True)
class OrderStreamSignal:
    """Minimal, non-secret order notification retained in memory."""

    event_time_ms: int
    transaction_time_ms: int
    symbol: str
    order_id: int
    client_order_id: str
    execution_type: str
    order_status: str
    trade_id: int
    last_quantity: str
    cumulative_quantity: str
    received_time_ms: int

    @property
    def dedupe_key(self) -> tuple[object, ...]:
        return (
            self.symbol,
            self.order_id,
            self.trade_id,
            self.execution_type,
            self.order_status,
            self.cumulative_quantity,
            self.event_time_ms,
        )


def parse_order_signal(
    payload: Mapping[str, object],
    *,
    received_time_ms: int | None = None,
) -> Optional[OrderStreamSignal]:
    """Parse one JSON event envelope; ignore balances and unknown event types."""
    event_raw = payload.get("event", payload)
    if not isinstance(event_raw, Mapping):
        return None
    if str(event_raw.get("e", "")) != ORDER_EVENT_TYPE:
        return None
    try:
        signal = OrderStreamSignal(
            event_time_ms=int(event_raw.get("E", 0) or 0),
            transaction_time_ms=int(event_raw.get("T", 0) or 0),
            symbol=str(event_raw.get("s", "")).upper(),
            order_id=int(event_raw.get("i", 0) or 0),
            client_order_id=str(event_raw.get("c", "")),
            execution_type=str(event_raw.get("x", "")).upper(),
            order_status=str(event_raw.get("X", "")).upper(),
            trade_id=int(event_raw.get("t", -1) or -1),
            last_quantity=str(event_raw.get("l", "0")),
            cumulative_quantity=str(event_raw.get("z", "0")),
            received_time_ms=(
                int(received_time_ms)
                if received_time_ms is not None
                else int(time.time() * 1000)
            ),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if not signal.symbol or signal.order_id <= 0:
        return None
    return signal


class OrderEventMailbox:
    """Bounded, thread-safe and duplicate-resistant notification mailbox."""

    def __init__(self, max_events: int = 2048) -> None:
        self._events: deque[OrderStreamSignal] = deque(maxlen=max(1, max_events))
        self._seen: deque[tuple[object, ...]] = deque(maxlen=max(1, max_events * 2))
        self._seen_set: set[tuple[object, ...]] = set()
        self._lock = threading.Lock()

    def put(self, signal: OrderStreamSignal) -> bool:
        with self._lock:
            key = signal.dedupe_key
            if key in self._seen_set:
                return False
            if len(self._seen) == self._seen.maxlen:
                self._seen_set.discard(self._seen[0])
            self._seen.append(key)
            self._seen_set.add(key)
            self._events.append(signal)
            return True

    def consume_for(self, order_ids: Iterable[int]) -> list[OrderStreamSignal]:
        wanted = {int(order_id) for order_id in order_ids}
        if not wanted:
            return []
        with self._lock:
            matching = [event for event in self._events if event.order_id in wanted]
            if matching:
                self._events = deque(
                    (event for event in self._events if event.order_id not in wanted),
                    maxlen=self._events.maxlen,
                )
            return matching


def reconciliation_due(
    poll_ticks: int,
    poll_interval: int,
    stream_events: Iterable[OrderStreamSignal],
) -> bool:
    """Keep periodic REST polling while allowing a stream event to wake it early."""
    return bool(list(stream_events)) or poll_ticks >= max(1, poll_interval)


def signed_subscription_request(
    api_key: str,
    api_secret: str,
    *,
    timestamp_ms: int,
    recv_window_ms: int = 5000,
) -> dict[str, object]:
    """Build the HMAC signature subscription documented by Binance Spot."""
    if not api_key or not api_secret:
        raise ValueError("User Data Stream requires API key and secret")
    params: dict[str, object] = {
        "apiKey": api_key,
        "recvWindow": max(1, min(60_000, int(recv_window_ms))),
        "timestamp": int(timestamp_ms),
    }
    canonical = "&".join(
        f"{name}={params[name]}" for name in sorted(params)
    )
    params["signature"] = hmac.new(
        api_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "id": uuid.uuid4().hex,
        "method": "userDataStream.subscribe.signature",
        "params": params,
    }


def websocket_api_url(rest_base_url: str) -> str:
    """Map the supported Spot REST venues to their WebSocket API endpoint."""
    if "testnet.binance.vision" in rest_base_url.lower():
        return "wss://ws-api.testnet.binance.vision/ws-api/v3"
    return "wss://ws-api.binance.com:443/ws-api/v3"


class BinanceUserDataObserver:
    """Reconnectable observer whose events only wake REST reconciliation."""

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        rest_base_url: str,
        mailbox: OrderEventMailbox,
        logger: Callable[[str], None],
        state_path: Optional[Path] = None,
        connect: Optional[Callable[..., object]] = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.url = websocket_api_url(rest_base_url)
        self.mailbox = mailbox
        self.logger = logger
        self.state_path = state_path
        self._connect = connect
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connection: Optional[object] = None
        self._state = {
            "state": "stopped",
            "connected_at": None,
            "last_event_at": None,
            "last_order_event_at": None,
            "reconnects": 0,
            "order_events": 0,
            "duplicates": 0,
            "last_error": None,
        }

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="binance-user-stream-shadow",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._close_connection()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
        self._set_state(state="stopped")

    def _connector(self) -> Callable[..., object]:
        if self._connect is not None:
            return self._connect
        return create_connection

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._observe_connection()
                delay = 1.0
            except (
                OSError,
                RuntimeError,
                ValueError,
                TimeoutError,
                WebSocketException,
            ) as exc:
                self._close_connection()
                if self._stop.is_set():
                    break
                self._set_state(
                    state="reconnecting",
                    reconnects=int(self._state["reconnects"]) + 1,
                    last_error=type(exc).__name__,
                )
                self.logger(
                    f"[USER-STREAM] disconnected={type(exc).__name__}; "
                    "REST polling remains authoritative"
                )
                self._stop.wait(delay)
                delay = min(30.0, delay * 2.0)

    def _close_connection(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except (OSError, RuntimeError, WebSocketException):
            pass

    def _observe_connection(self) -> None:
        connection = self._connector()(self.url, timeout=10)
        self._connection = connection
        request = signed_subscription_request(
            self.api_key,
            self.api_secret,
            timestamp_ms=int(time.time() * 1000),
        )
        connection.send(json.dumps(request, separators=(",", ":")))
        response = json.loads(connection.recv())
        if int(response.get("status", 0) or 0) != 200:
            raise RuntimeError("User Data Stream subscription rejected")
        self._set_state(
            state="connected",
            connected_at=time.time(),
            last_error=None,
        )
        self.logger("[USER-STREAM] connected in SHADOW notification mode")

        while not self._stop.is_set():
            try:
                raw = connection.recv()
            except WebSocketTimeoutException:
                connection.ping()
                continue
            payload = json.loads(raw)
            event_raw = payload.get("event", payload)
            event_type = (
                str(event_raw.get("e", ""))
                if isinstance(event_raw, Mapping)
                else ""
            )
            now = time.time()
            self._set_state(last_event_at=now)
            if event_type in TERMINAL_EVENT_TYPES:
                raise RuntimeError(f"User Data Stream ended: {event_type}")
            signal = parse_order_signal(
                payload,
                received_time_ms=int(now * 1000),
            )
            if signal is None:
                continue
            accepted = self.mailbox.put(signal)
            self._set_state(
                last_order_event_at=now,
                order_events=int(self._state["order_events"]) + int(accepted),
                duplicates=int(self._state["duplicates"]) + int(not accepted),
            )

    def _set_state(self, **updates: object) -> None:
        self._state.update(updates)
        if self.state_path is None:
            return
        target = self.state_path
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(self._state, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        except OSError as exc:
            # The diagnostic file is optional. Losing it must not tear down a
            # healthy notification stream or affect authoritative REST polls.
            self.logger(
                f"[USER-STREAM] health snapshot unavailable={type(exc).__name__}"
            )
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def state(self) -> dict[str, object]:
        return dict(self._state)
