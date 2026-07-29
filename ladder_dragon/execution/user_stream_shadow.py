# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep notification-only account-stream soak independent of execution.
"""Read-only Binance User Data Stream soak service.

The observer cannot submit, cancel or replace an order. WebSocket events only
wake an authenticated GET so REST remains the authoritative source of truth.
Keeping this service outside the execution worker allows soak collection while
a persistent circuit HALT correctly prevents every trading worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import threading
import time
from typing import Callable, Iterable, Mapping

import requests

from ladder_dragon.execution import tools_market
from ladder_dragon.execution.user_stream import (
    BinanceUserDataObserver,
    OrderEventMailbox,
    OrderStreamSignal,
)


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{5,20}$")
READ_ERRORS = (
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    requests.RequestException,
)


@dataclass(frozen=True)
class UserStreamShadowConfig:
    """Validated configuration for one read-only stream observer."""

    symbol: str
    state_path: Path
    rest_poll_sec: float = 60.0

    def validate(self) -> None:
        if not SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError("invalid User Data Stream symbol")
        if self.rest_poll_sec < 5 or self.rest_poll_sec > 3600:
            raise ValueError("REST poll interval must be between 5 and 3600 seconds")


def reconcile_order_events(
    events: Iterable[OrderStreamSignal],
    *,
    signed_get: Callable[[str, Mapping[str, object]], object],
) -> int:
    """Confirm every distinct event order through a read-only Binance GET."""
    identities = sorted({(event.symbol, event.order_id) for event in events})
    for symbol, order_id in identities:
        payload = signed_get(
            "/api/v3/order",
            {"symbol": symbol, "orderId": order_id},
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("order reconciliation returned a non-object")
        if (
            str(payload.get("symbol") or "").upper() != symbol
            or int(payload.get("orderId") or 0) != order_id
        ):
            raise RuntimeError("order reconciliation identity mismatch")
    return len(identities)


def run_user_stream_shadow(
    config: UserStreamShadowConfig,
    *,
    stop_event: threading.Event,
    logger: Callable[[str], None] = print,
) -> int:
    """Run a bounded-I/O observer until systemd requests a clean stop."""
    config.validate()
    if not tools_market.API_KEY or not tools_market.API_SECRET:
        raise RuntimeError("User Data Stream credentials are unavailable")

    mailbox = OrderEventMailbox()
    observer = BinanceUserDataObserver(
        api_key=tools_market.API_KEY,
        api_secret=tools_market.API_SECRET,
        rest_base_url=tools_market.BASE_URL,
        mailbox=mailbox,
        logger=logger,
        state_path=config.state_path,
        timestamp_ms=tools_market._timestamp_ms,
        state_persist_interval_sec=5,
        idle_timeout_sec=90,
    )
    observer.start()
    next_periodic_rest = 0.0
    try:
        while not stop_event.is_set():
            mailbox.wait(timeout=1.0)
            events = mailbox.consume_all()
            if events:
                try:
                    reconciled = reconcile_order_events(
                        events,
                        signed_get=tools_market._signed_get,
                    )
                except READ_ERRORS as exc:
                    logger(
                        "[USER-STREAM-SOAK] event REST reconciliation failed="
                        f"{type(exc).__name__}"
                    )
                else:
                    observer.record_rest_reconciliation(event_woken=True)
                    logger(
                        "[USER-STREAM-SOAK] event REST reconciliation "
                        f"confirmed_orders={reconciled}"
                    )
            now = time.monotonic()
            if now >= next_periodic_rest:
                try:
                    payload = tools_market._signed_get(
                        "/api/v3/openOrders",
                        {"symbol": config.symbol},
                    )
                    if not isinstance(payload, list):
                        raise RuntimeError(
                            "open-order reconciliation returned a non-list"
                        )
                except READ_ERRORS as exc:
                    logger(
                        "[USER-STREAM-SOAK] periodic REST reconciliation "
                        f"failed={type(exc).__name__}"
                    )
                else:
                    observer.record_rest_reconciliation(event_woken=False)
                next_periodic_rest = now + config.rest_poll_sec
    finally:
        observer.stop()
    return 0
