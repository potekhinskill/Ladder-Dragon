# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: prove notification-only User Data Stream recovery on Testnet.
"""Controlled Testnet reconnect and event-to-REST verification."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from ladder_dragon.execution.user_stream import (
    BinanceUserDataObserver,
    OrderEventMailbox,
)
from ladder_dragon.execution.user_stream_shadow import reconcile_order_events


DRILL_ERRORS = (
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    requests.RequestException,
)


def _wait_for(
    predicate: Callable[[], bool],
    *,
    timeout_sec: float,
    description: str,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {description}")


def _cancel_testnet_order(
    client: Any,
    *,
    symbol: str,
    client_order_id: str,
) -> None:
    result = client.signed(
        "DELETE",
        "/api/v3/order",
        {"symbol": symbol, "origClientOrderId": client_order_id},
    )
    if not isinstance(result, dict) or str(
        result.get("status") or ""
    ).upper() != "CANCELED":
        raise RuntimeError("Testnet drill order cancellation is unconfirmed")


def execute_user_stream_drill(
    *,
    client: Any,
    symbol: str,
    order_params: dict[str, str],
    state_path: Path,
    clock_offset_ms: int,
    observer_factory: Any = BinanceUserDataObserver,
) -> dict[str, object]:
    """Prove Testnet reconnect and event-triggered authoritative REST."""
    parsed_base = urlsplit(str(client.base_url))
    if (
        parsed_base.scheme != "https"
        or parsed_base.hostname != "testnet.binance.vision"
        or parsed_base.port not in (None, 443)
        or parsed_base.username is not None
        or parsed_base.password is not None
        or parsed_base.query
        or parsed_base.fragment
    ):
        raise ValueError("User Data Stream drill requires Binance Spot Testnet")
    mailbox = OrderEventMailbox()
    observer = observer_factory(
        api_key=client.api_key,
        api_secret=client.api_secret,
        rest_base_url=client.base_url,
        mailbox=mailbox,
        logger=lambda _message: None,
        state_path=state_path,
        timestamp_ms=lambda: int(time.time() * 1000) + clock_offset_ms,
    )
    created: dict[str, Any] | None = None
    canceled = False
    primary_error: BaseException | None = None
    try:
        observer.start()
        _wait_for(
            lambda: observer.state().get("state") == "connected",
            timeout_sec=20,
            description="User Data Stream connection",
        )
        reconnects_before = int(observer.state().get("reconnects") or 0)
        observer.request_reconnect_drill()
        _wait_for(
            lambda: (
                observer.state().get("state") == "connected"
                and int(observer.state().get("reconnects") or 0)
                > reconnects_before
            ),
            timeout_sec=30,
            description="controlled User Data Stream reconnect",
        )
        created = client.signed("POST", "/api/v3/order", order_params)
        order_id = int(created.get("orderId") or 0)
        if order_id <= 0:
            raise RuntimeError("Testnet order response has no order ID")
        matched = []

        def event_received() -> bool:
            mailbox.wait(timeout=0.1)
            matched.extend(
                event for event in mailbox.consume_all()
                if event.symbol == symbol and event.order_id == order_id
            )
            return bool(matched)

        _wait_for(
            event_received,
            timeout_sec=20,
            description="Testnet order event",
        )
        confirmed = reconcile_order_events(
            matched,
            signed_get=lambda path, params: client.signed(
                "GET", path, dict(params)
            ),
        )
        observer.record_rest_reconciliation(event_woken=True)
        client_id = str(
            created.get("clientOrderId") or order_params["newClientOrderId"]
        )
        _cancel_testnet_order(
            client,
            symbol=symbol,
            client_order_id=client_id,
        )
        canceled = True
        state = observer.state()
        return {
            "controlled_reconnects": (
                int(state.get("reconnects") or 0) - reconnects_before
            ),
            "order_events": len(matched),
            "event_woken_rest_reconciliations": confirmed,
            "rest_remains_authoritative": True,
            "order_cleanup": "canceled",
        }
    except DRILL_ERRORS as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            if created is not None and not canceled:
                client_id = str(
                    created.get("clientOrderId")
                    or order_params["newClientOrderId"]
                )
                _cancel_testnet_order(
                    client,
                    symbol=symbol,
                    client_order_id=client_id,
                )
        except DRILL_ERRORS as exc:
            cleanup_error = exc
        finally:
            observer.stop()
        if cleanup_error is not None:
            if primary_error is not None:
                raise primary_error from cleanup_error
            raise RuntimeError(
                "Testnet drill cleanup could not be confirmed"
            ) from cleanup_error


__all__ = ["execute_user_stream_drill"]
