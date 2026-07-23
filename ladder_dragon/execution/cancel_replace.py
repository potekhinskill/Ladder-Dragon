# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: atomically re-anchor one unfilled BUY with durable reconciliation.
"""Fail-closed Binance cancelReplace for bounded BUY re-anchors."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import time
from typing import Any, Callable, Dict, Mapping

import requests

from ladder_dragon.execution.order_identity import client_order_id
from ladder_dragon.execution.order_recovery import (
    OrderJournal,
    TERMINAL_EXCHANGE_STATES,
)


@dataclass(frozen=True)
class CancelReplaceDependencies:
    journal: Callable[[], OrderJournal | None]
    signed_request: Callable[..., Any]
    get_order_by_id: Callable[[str, int], Dict[str, Any] | None]
    get_order_by_client_id: Callable[[str, str], Dict[str, Any] | None]
    halt: Callable[..., None]
    logger: Callable[[str], None]


def _active(payload: Mapping[str, object] | None) -> bool:
    return isinstance(payload, Mapping) and str(
        payload.get("status") or ""
    ).upper() in {"NEW", "PARTIALLY_FILLED"}


def atomic_cancel_replace_buy(
    symbol: str,
    original_order: Mapping[str, object],
    target_price: object,
    *,
    maximum_notional: object,
    dependencies: CancelReplaceDependencies,
    latency_trace: Any | None = None,
) -> Dict[str, Any] | None:
    """Replace an exact zero-fill BUY once; reconcile every ambiguous result."""
    try:
        order_id = int(original_order.get("orderId") or 0)
        quantity = Decimal(str(original_order.get("origQty") or "0"))
        executed = Decimal(str(original_order.get("executedQty") or "0"))
        target = Decimal(str(target_price))
        cap = Decimal(str(maximum_notional))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("cancelReplace inputs are invalid") from exc
    if (
        order_id <= 0
        or str(original_order.get("side") or "").upper() != "BUY"
        or str(original_order.get("status") or "").upper() != "NEW"
        or executed != 0
        or any(
            not value.is_finite() or value <= 0
            for value in (quantity, target, cap)
        )
    ):
        raise ValueError("cancelReplace requires an exact zero-fill NEW BUY")
    if quantity * target > cap:
        raise ValueError("cancelReplace target exceeds the hard per-order CAP")
    journal = dependencies.journal()
    if journal is None:
        raise RuntimeError("cancelReplace requires the durable order journal")
    original_intent = journal.get_by_exchange_order_id(order_id)
    if original_intent is None:
        raise RuntimeError("cancelReplace original BUY is absent from journal")
    price_text = format(target, "f")
    quantity_text = format(quantity, "f")
    replacement_client_id = client_order_id(
        symbol,
        "BUY",
        f"reanchor:{order_id}",
        price_text,
        quantity_text,
        bucket_seconds=1,
    )
    if journal.get(replacement_client_id) is not None:
        replacement_client_id = client_order_id(
            symbol,
            "BUY",
            f"reanchor:{order_id}:{time.time_ns()}",
            price_text,
            quantity_text,
            bucket_seconds=1,
        )
    journal.prepare(
        client_order_id=replacement_client_id,
        symbol=symbol,
        side="BUY",
        purpose="adaptive-reanchor",
        order_type=str(original_order.get("type") or "LIMIT"),
        quantity=quantity_text,
        price=price_text,
        metadata={"replaces_exchange_order_id": order_id},
    )
    if latency_trace is not None:
        latency_trace.mark("journal_commit")
    params: Dict[str, object] = {
        "symbol": symbol,
        "side": "BUY",
        "cancelOrderId": order_id,
        "cancelReplaceMode": "STOP_ON_FAILURE",
        "cancelRestrictions": "ONLY_NEW",
        "type": str(original_order.get("type") or "LIMIT").upper(),
        "quantity": quantity_text,
        "price": price_text,
        "newClientOrderId": replacement_client_id,
        "newOrderRespType": "RESULT",
    }
    if params["type"] != "LIMIT_MAKER":
        params["timeInForce"] = str(
            original_order.get("timeInForce") or "GTC"
        )

    def reconcile() -> Dict[str, Any] | None:
        old = dependencies.get_order_by_id(symbol, order_id)
        new = dependencies.get_order_by_client_id(
            symbol,
            replacement_client_id,
        )
        old_status = str((old or {}).get("status") or "").upper()
        if old_status in TERMINAL_EXCHANGE_STATES and _active(new):
            journal.record_exchange_order(
                original_intent.client_order_id,
                dict(old),
            )
            journal.record_exchange_order(
                replacement_client_id,
                dict(new),
            )
            return dict(new)
        if old_status == "NEW" and new is None:
            journal.mark_failed(
                replacement_client_id,
                "exchange confirmed cancelReplace was not applied",
            )
            return None
        journal.mark_unknown(
            replacement_client_id,
            "cancelReplace reconciliation is ambiguous",
        )
        dependencies.halt(
            "cancelReplace outcome is ambiguous",
            symbol=symbol,
            order_id=order_id,
            client_order_id=replacement_client_id,
        )
        raise RuntimeError("cancelReplace outcome is ambiguous")

    try:
        if latency_trace is not None:
            latency_trace.mark("request_sent")
        payload = dependencies.signed_request(
            "POST",
            "/api/v3/order/cancelReplace",
            params,
        )
        if latency_trace is not None:
            latency_trace.mark("exchange_ack")
    except (requests.RequestException, RuntimeError):
        return reconcile()
    if (
        not isinstance(payload, dict)
        or payload.get("cancelResult") != "SUCCESS"
        or payload.get("newOrderResult") != "SUCCESS"
        or not isinstance(payload.get("cancelResponse"), dict)
        or not isinstance(payload.get("newOrderResponse"), dict)
    ):
        return reconcile()
    journal.record_exchange_order(
        original_intent.client_order_id,
        payload["cancelResponse"],
    )
    journal.record_exchange_order(
        replacement_client_id,
        payload["newOrderResponse"],
    )
    dependencies.logger(
        f"[CANCEL-REPLACE] {symbol} old={order_id} "
        f"new={payload['newOrderResponse'].get('orderId')}"
    )
    if latency_trace is not None:
        latency_trace.mark("cancel_replace_ack")
    return dict(payload["newOrderResponse"])
