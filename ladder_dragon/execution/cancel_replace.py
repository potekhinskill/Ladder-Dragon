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

_RECONCILIATION_QUERY_ERRORS = (
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    requests.RequestException,
)


@dataclass(frozen=True)
class CancelReplaceDependencies:
    journal: Callable[[], OrderJournal | None]
    signed_request: Callable[..., Any]
    get_order_by_id: Callable[[str, int], Dict[str, Any] | None]
    get_order_by_client_id: Callable[[str, str], Dict[str, Any] | None]
    halt: Callable[..., None]
    logger: Callable[[str], None]
    sleep: Callable[[float], None] = time.sleep
    reconcile_attempts: int = 4
    reconcile_delay_sec: float = 0.25


def _replacement_was_placed(
    payload: Mapping[str, object] | None,
) -> bool:
    return isinstance(payload, Mapping) and str(
        payload.get("status") or ""
    ).upper() in {"NEW", "PARTIALLY_FILLED", "FILLED"}


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

    def reconcile() -> Dict[str, Any]:
        attempts = max(1, int(dependencies.reconcile_attempts))
        delay = max(0.0, float(dependencies.reconcile_delay_sec))
        last_old_status = "UNKNOWN"
        last_new_status = "ABSENT"
        last_error = ""
        for attempt in range(attempts):
            try:
                old = dependencies.get_order_by_id(symbol, order_id)
                new = dependencies.get_order_by_client_id(
                    symbol,
                    replacement_client_id,
                )
                last_old_status = str(
                    (old or {}).get("status") or "ABSENT"
                ).upper()
                last_new_status = str(
                    (new or {}).get("status") or "ABSENT"
                ).upper()
                if (
                    last_old_status in TERMINAL_EXCHANGE_STATES
                    and _replacement_was_placed(new)
                ):
                    journal.record_exchange_order(
                        original_intent.client_order_id,
                        dict(old),
                    )
                    journal.record_exchange_order(
                        replacement_client_id,
                        dict(new),
                    )
                    dependencies.logger(
                        f"[CANCEL-REPLACE-RECOVERED] {symbol} "
                        f"old={order_id}:{last_old_status} "
                        f"new={new.get('orderId')}:{last_new_status} "
                        f"attempt={attempt + 1}"
                    )
                    return dict(new)
            except _RECONCILIATION_QUERY_ERRORS as exc:
                last_error = type(exc).__name__
            if attempt + 1 < attempts and delay > 0:
                dependencies.sleep(delay)

        # An old NEW order and an absent replacement are only one bounded
        # observation, not proof that a timed-out mutation never reached
        # Binance. Preserve the intent for startup recovery and stop mutations.
        diagnostic = (
            "cancelReplace reconciliation remained ambiguous "
            f"after {attempts} attempts; old={last_old_status}; "
            f"new={last_new_status}"
        )
        if last_error:
            diagnostic += f"; query_error={last_error}"
        journal.mark_unknown(
            replacement_client_id,
            diagnostic,
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
    if isinstance(payload, Mapping):
        cancel_result = str(
            payload.get("cancelResult") or ""
        ).upper()
        new_order_result = str(
            payload.get("newOrderResult") or ""
        ).upper()
        if (
            cancel_result == "FAILURE"
            and new_order_result == "NOT_ATTEMPTED"
        ):
            journal.mark_failed(
                replacement_client_id,
                "exchange rejected cancellation; replacement was not attempted",
            )
            dependencies.logger(
                f"[CANCEL-REPLACE-NOOP] {symbol} old={order_id} "
                "cancel=FAILURE new=NOT_ATTEMPTED"
            )
            return None
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
