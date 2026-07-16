"""Idempotent LIMIT and OCO placement for the symbol executor."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import requests

from order_identity import client_order_id
from order_recovery import OrderJournal, TERMINAL_EXCHANGE_STATES


@dataclass(frozen=True)
class OrderDependencies:
    live: Callable[[], bool]
    logger: Callable[[str], None]
    pull_filters: Callable[[str], Any]
    round_price: Callable[[str, float], float]
    round_qty: Callable[[str, float], float]
    min_qty: Callable[[str, float], float]
    min_notional: Callable[[str, float], float]
    format_price: Callable[[str, float], str]
    format_qty: Callable[[str, float], str]
    journal: Callable[[], OrderJournal | None]
    signed_request: Callable[..., Any]
    get_order_by_client_id: Callable[[str, str], Dict[str, Any] | None]
    get_order_list_by_client_id: Callable[[str], Dict[str, Any] | None]
    verify_oco_legs: Callable[[str, Dict[str, Any]], Any]
    cancel_oco: Callable[[str, int], None]
    halt: Callable[..., None]


def place_limit_order(
    side: str,
    symbol: str,
    quantity: float,
    price: float,
    *,
    dependencies: OrderDependencies,
    maker: bool = False,
    purpose: str = "ladder",
    parent_client_order_id: Optional[str] = None,
) -> Dict[str, Any] | None:
    if not dependencies.live():
        dependencies.logger(
            f"[DRY] skip LIMIT {symbol} {side.upper()} "
            f"{quantity:.8f} @ {price:.8f}"
        )
        return None
    dependencies.pull_filters(symbol)
    price = dependencies.round_price(symbol, price)
    quantity = dependencies.round_qty(symbol, quantity)

    if quantity < dependencies.min_qty(symbol, 0):
        return None
    if quantity * price < dependencies.min_notional(symbol, price):
        needed = dependencies.min_notional(symbol, price) / price
        needed = dependencies.round_qty(
            symbol, max(needed, dependencies.min_qty(symbol, 0))
        )
        if needed <= 0:
            return None
        quantity = needed

    quantity_text = dependencies.format_qty(symbol, quantity)
    price_text = dependencies.format_price(symbol, price)
    journal = dependencies.journal()
    active = (
        journal.find_active(
            symbol=symbol,
            side=side,
            purpose=purpose,
            quantity=quantity_text,
            price=price_text,
        )
        if journal is not None
        else None
    )
    if active is not None:
        try:
            existing = dependencies.get_order_by_client_id(
                symbol, active.client_order_id
            )
        except requests.RequestException as exc:
            journal.mark_unknown(active.client_order_id, exc)
            raise
        if existing is not None:
            updated = journal.record_exchange_order(
                active.client_order_id, existing
            )
            if updated.state not in TERMINAL_EXCHANGE_STATES:
                dependencies.logger(
                    f"[IDEMPOTENT] reuse {symbol} {side} "
                    f"client={active.client_order_id} "
                    f"order={updated.exchange_order_id} state={updated.state}"
                )
                return existing
            active = None

    generated_id = client_order_id(
        symbol, side, purpose, price_text, quantity_text
    )
    if journal is not None and journal.get(generated_id) is not None:
        generated_id = client_order_id(
            symbol,
            side,
            f"{purpose}-{time.time_ns()}",
            price_text,
            quantity_text,
            bucket_seconds=1,
        )
    order_client_id = (
        active.client_order_id if active is not None else generated_id
    )
    if journal is not None:
        journal.prepare(
            client_order_id=order_client_id,
            symbol=symbol,
            side=side,
            purpose=purpose,
            order_type=("LIMIT_MAKER" if maker else "LIMIT"),
            quantity=quantity_text,
            price=price_text,
            parent_client_order_id=parent_client_order_id,
        )

    params = {
        "symbol": symbol,
        "side": side,
        "type": ("LIMIT_MAKER" if maker else "LIMIT"),
        "quantity": quantity_text,
        "price": price_text,
        "newOrderRespType": "RESULT",
        "newClientOrderId": order_client_id,
    }
    if not maker:
        params["timeInForce"] = "GTC"

    try:
        payload = dependencies.signed_request(
            "POST", "/api/v3/order", params
        )
        if isinstance(payload, dict):
            payload.setdefault("clientOrderId", order_client_id)
            if journal is not None:
                journal.record_exchange_order(order_client_id, payload)
        order_id = payload.get("orderId")
        dependencies.logger(
            f"[PLACE] {symbol} {side} {quantity_text} @ {price_text} "
            f"client={order_client_id} order={order_id}"
        )
        return payload
    except requests.RequestException as exc:
        if journal is not None:
            journal.mark_unknown(order_client_id, exc)
            try:
                reconciled = dependencies.get_order_by_client_id(
                    symbol, order_client_id
                )
            except requests.RequestException:
                reconciled = None
            if reconciled is not None:
                journal.record_exchange_order(order_client_id, reconciled)
                dependencies.logger(
                    f"[IDEMPOTENT] recovered uncertain POST "
                    f"client={order_client_id}"
                )
                return reconciled
            dependencies.halt(
                f"uncertain order submission has no exchange confirmation: "
                f"{order_client_id}",
                symbol=symbol,
                side=side,
                client_order_id=order_client_id,
            )
        try:
            error = exc.response.json()
            dependencies.logger(
                f"[ERR] place_limit_order: HTTP "
                f"{exc.response.status_code} {json.dumps(error)}"
            )
        except Exception:
            dependencies.logger(f"[ERR] place_limit_order: {exc}")
        raise


def place_oco_sell(
    symbol: str,
    quantity: float,
    tp_limit_price: float,
    sl_stop_price: float,
    sl_limit_price: float,
    *,
    dependencies: OrderDependencies,
    parent_client_order_id: Optional[str] = None,
) -> Dict[str, Any] | None:
    if not dependencies.live():
        dependencies.logger(
            f"[DRY] skip OCO {symbol} SELL {quantity:.8f}"
        )
        return None
    dependencies.pull_filters(symbol)
    quantity_text = dependencies.format_qty(
        symbol, dependencies.round_qty(symbol, quantity)
    )
    tp_text = dependencies.format_price(
        symbol, dependencies.round_price(symbol, tp_limit_price)
    )
    stop_text = dependencies.format_price(
        symbol, dependencies.round_price(symbol, sl_stop_price)
    )
    limit_text = dependencies.format_price(
        symbol, dependencies.round_price(symbol, sl_limit_price)
    )

    journal = dependencies.journal()
    purpose = (
        f"oco:{parent_client_order_id[:12]}"
        if parent_client_order_id
        else "oco"
    )
    active = (
        journal.find_active(
            symbol=symbol,
            side="SELL",
            purpose=purpose,
            quantity=quantity_text,
            price=tp_text,
        )
        if journal is not None
        else None
    )
    list_client_id = (
        active.client_order_id
        if active is not None
        else client_order_id(
            symbol, "SELL", purpose, tp_text, quantity_text
        )
    )
    if active is not None:
        existing = dependencies.get_order_list_by_client_id(list_client_id)
        if (
            isinstance(existing, dict)
            and existing.get("listStatusType") in ("EXEC_STARTED", "ALL_DONE")
        ):
            order_list_id = existing.get("orderListId")
            try:
                dependencies.verify_oco_legs(symbol, existing)
            except (requests.RequestException, RuntimeError):
                if order_list_id is not None:
                    dependencies.cancel_oco(symbol, int(order_list_id))
                raise
            if journal is not None:
                journal.record_order_list(list_client_id, existing)
                if parent_client_order_id:
                    journal.mark_protected(
                        parent_client_order_id=parent_client_order_id,
                        protection_client_order_id=list_client_id,
                        order_list_id=(
                            int(order_list_id)
                            if order_list_id is not None
                            else None
                        ),
                    )
            dependencies.logger(
                f"[IDEMPOTENT] reuse OCO {symbol} "
                f"client={list_client_id} list={order_list_id}"
            )
            return existing
    if (
        active is None
        and journal is not None
        and journal.get(list_client_id) is not None
    ):
        list_client_id = client_order_id(
            symbol,
            "SELL",
            f"{purpose}-{time.time_ns()}",
            tp_text,
            quantity_text,
            bucket_seconds=1,
        )
    if journal is not None:
        journal.prepare(
            client_order_id=list_client_id,
            symbol=symbol,
            side="SELL",
            purpose=purpose,
            order_type="OCO",
            quantity=quantity_text,
            price=tp_text,
            parent_client_order_id=parent_client_order_id,
            metadata={
                "stopPrice": stop_text,
                "stopLimitPrice": limit_text,
            },
        )
        if parent_client_order_id:
            journal.mark_protection_pending(parent_client_order_id)

    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity": quantity_text,
        "aboveType": "LIMIT_MAKER",
        "abovePrice": tp_text,
        "belowType": "STOP_LOSS_LIMIT",
        "belowStopPrice": stop_text,
        "belowPrice": limit_text,
        "belowTimeInForce": "GTC",
        "newOrderRespType": "RESULT",
        "listClientOrderId": list_client_id,
        "aboveClientOrderId": client_order_id(
            symbol, "SELL", "otp", tp_text, quantity_text
        ),
        "belowClientOrderId": client_order_id(
            symbol, "SELL", "osl", stop_text, quantity_text
        ),
    }
    try:
        payload = dependencies.signed_request(
            "POST", "/api/v3/orderList/oco", params
        )
        order_list_id = (
            payload.get("orderListId")
            if isinstance(payload, dict)
            else None
        )
        if order_list_id is None:
            raise RuntimeError("OCO response has no orderListId")
        verified = dependencies.signed_request(
            "GET",
            "/api/v3/orderList",
            {"orderListId": int(order_list_id)},
        )
        if (
            not isinstance(verified, dict)
            or verified.get("listStatusType")
            not in ("EXEC_STARTED", "ALL_DONE")
        ):
            raise RuntimeError(f"OCO verification failed: {verified}")
        try:
            dependencies.verify_oco_legs(symbol, verified)
        except (requests.RequestException, RuntimeError):
            try:
                dependencies.signed_request(
                    "DELETE",
                    "/api/v3/orderList",
                    {
                        "symbol": symbol,
                        "orderListId": int(order_list_id),
                    },
                )
            except requests.RequestException:
                pass
            raise
        if isinstance(payload, dict):
            payload.setdefault("listClientOrderId", list_client_id)
        if journal is not None:
            journal.record_order_list(list_client_id, verified)
            if parent_client_order_id:
                journal.mark_protected(
                    parent_client_order_id=parent_client_order_id,
                    protection_client_order_id=list_client_id,
                    order_list_id=int(order_list_id),
                )
        dependencies.logger(
            f"[ATTACH-OCO] {symbol} SELL {quantity_text} | "
            f"TP={tp_text} / SL stop={stop_text} "
            f"limit={limit_text} verified"
        )
        return payload
    except (requests.RequestException, RuntimeError) as exc:
        if journal is not None:
            journal.mark_unknown(list_client_id, exc)
            try:
                reconciled = dependencies.get_order_list_by_client_id(
                    list_client_id
                )
            except requests.RequestException:
                reconciled = None
            if (
                isinstance(reconciled, dict)
                and reconciled.get("listStatusType")
                in ("EXEC_STARTED", "ALL_DONE")
            ):
                order_list_id = reconciled.get("orderListId")
                try:
                    dependencies.verify_oco_legs(symbol, reconciled)
                except (requests.RequestException, RuntimeError) as verify_exc:
                    dependencies.logger(
                        f"[ERR] recovered OCO leg verification failed: "
                        f"{verify_exc}"
                    )
                    return None
                journal.record_order_list(list_client_id, reconciled)
                if parent_client_order_id:
                    journal.mark_protected(
                        parent_client_order_id=parent_client_order_id,
                        protection_client_order_id=list_client_id,
                        order_list_id=(
                            int(order_list_id)
                            if order_list_id is not None
                            else None
                        ),
                    )
                dependencies.logger(
                    f"[IDEMPOTENT] recovered uncertain OCO POST "
                    f"client={list_client_id}"
                )
                return reconciled
        try:
            error = exc.response.json()
            dependencies.logger(
                f"[ERR] place_oco_sell: HTTP "
                f"{exc.response.status_code} {json.dumps(error)}"
            )
        except (AttributeError, ValueError):
            dependencies.logger(f"[ERR] place_oco_sell: {exc}")
        return None
