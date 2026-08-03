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
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from websocket import ABNF, WebSocketException, WebSocketTimeoutException, create_connection


TERMINAL_EVENT_TYPES = {"eventStreamTerminated", "serverShutdown"}
ORDER_EVENT_TYPE = "executionReport"
PERSISTED_COUNTERS = (
    "reconnects",
    "idle_reconnects",
    "transport_failure_reconnects",
    "controlled_reconnect_drills",
    "connection_attempts",
    "sessions",
    "disconnects",
    "order_events",
    "duplicates",
    "out_of_order_events",
    "rest_reconciliations",
    "event_woken_rest_reconciliations",
    "bad_frames",
)
CURRENT_USER_STREAM_SOAK_EPOCH_ID = "transport-stability-2026-08-v1"
MAX_USER_STREAM_SOAK_EPOCHS = 64
_SOAK_EPOCH_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


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
    side: str
    order_price: str
    original_quantity: str
    last_price: str
    last_quantity: str
    cumulative_quantity: str
    cumulative_quote: str
    commission_amount: str
    commission_asset: str
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
            side=str(event_raw.get("S", "")).upper(),
            order_price=str(event_raw.get("p", "0")),
            original_quantity=str(event_raw.get("q", "0")),
            last_price=str(event_raw.get("L", "0")),
            last_quantity=str(event_raw.get("l", "0")),
            cumulative_quantity=str(event_raw.get("z", "0")),
            cumulative_quote=str(event_raw.get("Z", "0")),
            commission_amount=str(event_raw.get("n", "0") or "0"),
            commission_asset=str(event_raw.get("N", "") or "").upper(),
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
        self._condition = threading.Condition()

    def put(self, signal: OrderStreamSignal) -> bool:
        with self._condition:
            key = signal.dedupe_key
            if key in self._seen_set:
                return False
            if len(self._seen) == self._seen.maxlen:
                self._seen_set.discard(self._seen[0])
            self._seen.append(key)
            self._seen_set.add(key)
            self._events.append(signal)
            self._condition.notify_all()
            return True

    def consume_for(self, order_ids: Iterable[int]) -> list[OrderStreamSignal]:
        wanted = {int(order_id) for order_id in order_ids}
        if not wanted:
            return []
        with self._condition:
            matching = [event for event in self._events if event.order_id in wanted]
            if matching:
                self._events = deque(
                    (event for event in self._events if event.order_id not in wanted),
                    maxlen=self._events.maxlen,
                )
            return matching

    def consume_all(self) -> list[OrderStreamSignal]:
        """Drain all accepted notifications for a read-only reconciliation loop."""
        with self._condition:
            events = list(self._events)
            self._events.clear()
            return events

    def wait(self, timeout: float) -> bool:
        """Wait until any new order event arrives or the timeout expires."""
        with self._condition:
            if self._events:
                return True
            return bool(self._condition.wait(timeout=max(0.0, float(timeout))))

    def wait_for(self, order_ids: Iterable[int], timeout: float) -> bool:
        """Wait only for tracked orders so unrelated events cannot spin a worker."""
        wanted = {int(order_id) for order_id in order_ids}
        if not wanted:
            return False

        def matching_event_exists() -> bool:
            return any(event.order_id in wanted for event in self._events)

        with self._condition:
            return bool(
                self._condition.wait_for(
                    matching_event_exists,
                    timeout=max(0.0, float(timeout)),
                )
            )


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
        timestamp_ms: Optional[Callable[[], int]] = None,
        state_persist_interval_sec: float = 5.0,
        idle_timeout_sec: float = 90.0,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.url = websocket_api_url(rest_base_url)
        self.mailbox = mailbox
        self.logger = logger
        self.state_path = state_path
        self._connect = connect
        self._timestamp_ms = timestamp_ms or (
            lambda: int(time.time() * 1000)
        )
        self._state_persist_interval_sec = max(
            0.1, float(state_persist_interval_sec)
        )
        self._idle_timeout_sec = max(1.0, float(idle_timeout_sec))
        self._clock = clock
        self._monotonic = monotonic
        self._last_persist_monotonic: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connection: Optional[object] = None
        self._controlled_reconnect_pending = threading.Event()
        self._state_lock = threading.RLock()
        now = self._clock()
        self._state = {
            "state": "stopped",
            "first_observed_at": now,
            "connected_at": None,
            "last_transport_activity_at": None,
            "last_event_at": None,
            "last_order_event_at": None,
            "reconnects": 0,
            "idle_reconnects": 0,
            "transport_failure_reconnects": 0,
            "controlled_reconnect_drills": 0,
            "connection_attempts": 0,
            "sessions": 0,
            "disconnects": 0,
            "order_events": 0,
            "duplicates": 0,
            "out_of_order_events": 0,
            "rest_reconciliations": 0,
            "event_woken_rest_reconciliations": 0,
            "bad_frames": 0,
            "last_exchange_event_time_ms": None,
            "last_error": None,
            "current_soak_epoch_id": CURRENT_USER_STREAM_SOAK_EPOCH_ID,
            "soak_epochs": [],
            "soak_epoch_error": None,
        }
        self._restore_sanitized_state()
        self._ensure_current_soak_epoch(now)

    def _restore_sanitized_state(self) -> None:
        """Carry non-secret soak counters across short executor sessions."""
        path = self.state_path
        if path is None:
            return
        try:
            if not path.is_file() or path.stat().st_size > 65_536:
                return
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, Mapping):
            return
        for name in PERSISTED_COUNTERS:
            try:
                value = int(payload.get(name, 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= value <= 2**63 - 1:
                self._state[name] = value
        for name in (
            "first_observed_at",
            "last_transport_activity_at",
            "last_event_at",
            "last_order_event_at",
        ):
            try:
                value = float(payload.get(name))
            except (TypeError, ValueError, OverflowError):
                continue
            if value > 0 and value == value and value != float("inf"):
                self._state[name] = value
        try:
            exchange_time = int(
                payload.get("last_exchange_event_time_ms") or 0
            )
        except (TypeError, ValueError, OverflowError):
            exchange_time = 0
        if exchange_time > 0:
            self._state["last_exchange_event_time_ms"] = exchange_time
        raw_epochs = payload.get("soak_epochs")
        if raw_epochs is None:
            return
        try:
            self._state["soak_epochs"] = self._validated_soak_epochs(raw_epochs)
        except (TypeError, ValueError, OverflowError):
            # Keep the transport available, but make readiness fail closed.
            self._state["soak_epoch_error"] = "invalid persisted soak epoch evidence"

    def _validated_soak_epochs(self, raw_epochs: object) -> list[dict[str, object]]:
        """Validate append-only epoch baselines without accepting unknown fields."""
        if not isinstance(raw_epochs, list):
            raise TypeError("soak epochs must be a list")
        if len(raw_epochs) > MAX_USER_STREAM_SOAK_EPOCHS:
            raise ValueError("too many soak epochs")
        validated: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        previous_started_at = 0.0
        for raw_epoch in raw_epochs:
            if not isinstance(raw_epoch, Mapping):
                raise TypeError("soak epoch must be an object")
            if set(raw_epoch) != {"id", "started_at", "baseline"}:
                raise ValueError("soak epoch fields are invalid")
            epoch_id = str(raw_epoch.get("id") or "")
            if not _SOAK_EPOCH_ID.fullmatch(epoch_id) or epoch_id in seen_ids:
                raise ValueError("invalid or duplicate soak epoch id")
            started_at = float(raw_epoch.get("started_at") or 0)
            if (
                started_at <= previous_started_at
                or not math.isfinite(started_at)
            ):
                raise ValueError("invalid soak epoch start")
            raw_baseline = raw_epoch.get("baseline")
            if not isinstance(raw_baseline, Mapping):
                raise TypeError("soak epoch baseline must be an object")
            if set(raw_baseline) != set(PERSISTED_COUNTERS):
                raise ValueError("soak epoch baseline fields are invalid")
            baseline: dict[str, int] = {}
            for name in PERSISTED_COUNTERS:
                value = int(raw_baseline.get(name, -1))
                current = int(self._state[name])
                if value < 0 or value > current:
                    raise ValueError("invalid soak epoch counter baseline")
                baseline[name] = value
            seen_ids.add(epoch_id)
            previous_started_at = started_at
            validated.append({
                "id": epoch_id,
                "started_at": started_at,
                "baseline": baseline,
            })
        return validated

    def _ensure_current_soak_epoch(self, now: float) -> None:
        """Append one immutable baseline when the reviewed epoch identifier changes."""
        if self._state["soak_epoch_error"] is not None:
            return
        epochs = self._state["soak_epochs"]
        if not isinstance(epochs, list):
            self._state["soak_epoch_error"] = "invalid in-memory soak epoch evidence"
            return
        matches = [
            row for row in epochs
            if row.get("id") == CURRENT_USER_STREAM_SOAK_EPOCH_ID
        ]
        if len(matches) == 1:
            if epochs[-1] is matches[0]:
                return
            self._state["soak_epoch_error"] = "current soak epoch is not latest"
            return
        if matches or len(epochs) >= MAX_USER_STREAM_SOAK_EPOCHS:
            self._state["soak_epoch_error"] = "soak epoch history cannot accept a new epoch"
            return
        if (
            not math.isfinite(now)
            or now <= 0
            or (epochs and now <= float(epochs[-1]["started_at"]))
        ):
            self._state["soak_epoch_error"] = "new soak epoch start is invalid"
            return
        epochs.append({
            "id": CURRENT_USER_STREAM_SOAK_EPOCH_ID,
            "started_at": float(now),
            "baseline": {
                name: int(self._state[name]) for name in PERSISTED_COUNTERS
            },
        })

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
        self._set_state(state="stopped", force_persist=True)

    def request_reconnect_drill(self) -> None:
        """Close one connected socket to prove bounded automatic recovery."""
        if self._state_value("state") != "connected":
            raise RuntimeError("User Data Stream is not connected")
        self._set_state(
            controlled_reconnect_drills=(
                int(self._state_value("controlled_reconnect_drills")) + 1
            ),
            force_persist=True,
        )
        self._controlled_reconnect_pending.set()
        self._close_connection()

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
                controlled = self._controlled_reconnect_pending.is_set()
                self._controlled_reconnect_pending.clear()
                idle = isinstance(exc, TimeoutError)
                expected = controlled or idle
                self._set_state(
                    state="reconnecting",
                    reconnects=int(self._state_value("reconnects")) + 1,
                    idle_reconnects=(
                        int(self._state_value("idle_reconnects")) + int(idle)
                    ),
                    transport_failure_reconnects=(
                        int(self._state_value("transport_failure_reconnects"))
                        + int(not expected)
                    ),
                    disconnects=int(self._state_value("disconnects")) + 1,
                    last_error=None if expected else type(exc).__name__,
                    force_persist=True,
                )
                reason = (
                    "controlled" if controlled
                    else "idle" if idle else type(exc).__name__
                )
                self.logger(
                    f"[USER-STREAM] reconnect={reason}; "
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
        self._set_state(
            connection_attempts=(
                int(self._state_value("connection_attempts")) + 1
            ),
        )
        connection = self._connector()(self.url, timeout=10)
        self._connection = connection
        request = signed_subscription_request(
            self.api_key,
            self.api_secret,
            timestamp_ms=int(self._timestamp_ms()),
        )
        connection.send(json.dumps(request, separators=(",", ":")))
        response = json.loads(connection.recv())
        if int(response.get("status", 0) or 0) != 200:
            raise RuntimeError("User Data Stream subscription rejected")
        self._set_state(
            state="connected",
            connected_at=self._clock(),
            last_transport_activity_at=self._clock(),
            sessions=int(self._state_value("sessions")) + 1,
            last_error=None,
            force_persist=True,
        )
        self.logger("[USER-STREAM] connected in SHADOW notification mode")
        last_frame_monotonic = self._monotonic()

        while not self._stop.is_set():
            try:
                receive_frame = getattr(connection, "recv_data_frame", None)
                if callable(receive_frame):
                    opcode, frame = receive_frame(control_frame=True)
                    last_frame_monotonic = self._monotonic()
                    if opcode in (ABNF.OPCODE_PING, ABNF.OPCODE_PONG):
                        # websocket-client answers server PING frames itself.
                        # Reading control frames here proves transport activity;
                        # otherwise a healthy quiet account looks disconnected.
                        self._set_state(
                            last_transport_activity_at=self._clock()
                        )
                        continue
                    if opcode == ABNF.OPCODE_CLOSE:
                        raise RuntimeError("User Data Stream transport closed")
                    raw = frame.data
                else:
                    # Test and compatibility transports may expose only recv().
                    raw = connection.recv()
                    last_frame_monotonic = self._monotonic()
            except WebSocketTimeoutException:
                idle_for = self._monotonic() - last_frame_monotonic
                if idle_for >= self._idle_timeout_sec:
                    raise TimeoutError(
                        "User Data Stream exceeded the silent-session deadline"
                    )
                connection.ping()
                continue
            now = self._clock()
            self._set_state(last_transport_activity_at=now)
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError, UnicodeError):
                self._set_state(
                    last_event_at=now,
                    bad_frames=int(self._state_value("bad_frames")) + 1,
                    force_persist=True,
                )
                self.logger(
                    "[USER-STREAM] discarded malformed frame; "
                    "REST polling remains authoritative"
                )
                continue
            if not isinstance(payload, Mapping):
                self._set_state(
                    last_event_at=now,
                    bad_frames=int(self._state_value("bad_frames")) + 1,
                    force_persist=True,
                )
                self.logger(
                    "[USER-STREAM] discarded non-object frame; "
                    "REST polling remains authoritative"
                )
                continue
            event_raw = payload.get("event", payload)
            event_type = (
                str(event_raw.get("e", ""))
                if isinstance(event_raw, Mapping)
                else ""
            )
            self._set_state(last_event_at=now)
            if event_type in TERMINAL_EVENT_TYPES:
                raise RuntimeError(f"User Data Stream ended: {event_type}")
            signal = parse_order_signal(
                payload,
                received_time_ms=int(now * 1000),
            )
            if signal is None:
                continue
            previous_event_time = self._state_value(
                "last_exchange_event_time_ms"
            )
            out_of_order = (
                previous_event_time is not None
                and signal.event_time_ms < int(previous_event_time)
            )
            accepted = self.mailbox.put(signal)
            self._set_state(
                last_order_event_at=now,
                order_events=(
                    int(self._state_value("order_events")) + int(accepted)
                ),
                duplicates=(
                    int(self._state_value("duplicates")) + int(not accepted)
                ),
                out_of_order_events=(
                    int(self._state_value("out_of_order_events"))
                    + int(out_of_order and accepted)
                ),
                last_exchange_event_time_ms=max(
                    int(previous_event_time or 0), signal.event_time_ms
                ),
                force_persist=True,
            )

    def _set_state(
        self,
        *,
        force_persist: bool = False,
        **updates: object,
    ) -> None:
        with self._state_lock:
            self._state.update(updates)
            if self.state_path is None:
                return
            persist_now = self._monotonic()
            if (
                not force_persist
                and self._last_persist_monotonic is not None
                and persist_now - self._last_persist_monotonic
                < self._state_persist_interval_sec
            ):
                return
            # Rate-limit failed writes too; a read-only filesystem must not
            # create an error and I/O storm in the notification thread.
            self._last_persist_monotonic = persist_now
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
                # The diagnostic file is optional. Losing it must not tear
                # down a healthy stream or affect authoritative REST polls.
                self.logger(
                    "[USER-STREAM] health snapshot unavailable="
                    f"{type(exc).__name__}"
                )
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _state_value(self, name: str) -> object:
        with self._state_lock:
            return self._state[name]

    def state(self) -> dict[str, object]:
        with self._state_lock:
            return dict(self._state)

    def record_rest_reconciliation(self, *, event_woken: bool) -> None:
        """Persist proof that an authoritative REST check followed polling or WS."""
        self._set_state(
            rest_reconciliations=(
                int(self._state_value("rest_reconciliations")) + 1
            ),
            event_woken_rest_reconciliations=(
                int(self._state_value("event_woken_rest_reconciliations"))
                + int(event_woken)
            ),
            force_persist=True,
        )
