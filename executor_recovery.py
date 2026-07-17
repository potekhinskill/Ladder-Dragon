# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Запросы, отмена, проверка ордеров и восстановление после рестарта."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests

from order_recovery import OrderIntent, OrderJournal


def http_error_code(exc: requests.HTTPError) -> Optional[int]:
    try:
        payload = exc.response.json()
        return int(payload.get("code")) if isinstance(payload, dict) else None
    except (AttributeError, TypeError, ValueError):
        return None


def list_open_orders(
    symbol: str,
    *,
    signed_request: Callable[..., Any],
    logger: Callable[[str], None],
) -> List[Dict[str, Any]]:
    try:
        return signed_request("GET", "/api/v3/openOrders", {"symbol": symbol}) or []
    except Exception as exc:
        logger(f"[ERR] list_open_orders: {exc}")
        return []


def cancel_order(
    symbol: str,
    order_id: int,
    *,
    signed_request: Callable[..., Any],
    logger: Callable[[str], None],
) -> None:
    try:
        signed_request(
            "DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}
        )
        logger(f"[CANCEL] {symbol} order {order_id}")
    except Exception as exc:
        logger(f"[ERR] cancel_order: {exc}")


def cancel_oco(
    symbol: str,
    order_list_id: int,
    *,
    signed_request: Callable[..., Any],
    logger: Callable[[str], None],
) -> None:
    try:
        signed_request(
            "DELETE",
            "/api/v3/orderList",
            {"symbol": symbol, "orderListId": int(order_list_id)},
        )
        logger(f"[CANCEL-OCO] {symbol} orderListId={order_list_id}")
    except Exception as exc:
        logger(f"[ERR] cancel_oco: {exc}")


def get_order_by_client_id(
    symbol: str,
    client_id: str,
    *,
    signed_request: Callable[..., Any],
) -> Dict[str, Any] | None:
    try:
        return signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "origClientOrderId": client_id},
        )
    except requests.HTTPError as exc:
        if http_error_code(exc) == -2013:
            return None
        raise


def get_order_list_by_client_id(
    client_id: str,
    *,
    signed_request: Callable[..., Any],
) -> Dict[str, Any] | None:
    try:
        return signed_request(
            "GET", "/api/v3/orderList", {"origClientOrderId": client_id}
        )
    except requests.HTTPError as exc:
        if http_error_code(exc) in (-2013, -2011):
            return None
        raise


def verify_oco_legs(
    symbol: str,
    order_list: Dict[str, Any],
    *,
    signed_request: Callable[..., Any],
) -> List[Dict[str, Any]]:
    """Подтвердить, что OCO содержит ровно TP- и SL-ногу стороны SELL."""
    refs = order_list.get("orders") or []
    if len(refs) != 2:
        raise RuntimeError("OCO verification did not return exactly two legs")
    legs: List[Dict[str, Any]] = []
    for ref in refs:
        if ref.get("orderId") is None:
            raise RuntimeError("OCO leg has no orderId")
        payload = signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "orderId": int(ref["orderId"])},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("OCO leg query returned an invalid payload")
        legs.append(payload)
    if any(str(leg.get("side") or "").upper() != "SELL" for leg in legs):
        raise RuntimeError("OCO contains a non-SELL leg")
    leg_types = {str(leg.get("type") or "").upper() for leg in legs}
    if not ({"LIMIT_MAKER", "LIMIT"} & leg_types) or not (
        {"STOP_LOSS_LIMIT", "STOP_LOSS"} & leg_types
    ):
        raise RuntimeError(f"OCO leg types are invalid: {sorted(leg_types)}")
    return legs


def record_order_payload(
    payload: Dict[str, Any] | None,
    *,
    journal: OrderJournal | None,
) -> Optional[OrderIntent]:
    if not payload or journal is None:
        return None
    client_id = str(
        payload.get("clientOrderId") or payload.get("origClientOrderId") or ""
    )
    intent = journal.get(client_id) if client_id else None
    if intent is None and payload.get("orderId") is not None:
        intent = journal.get_by_exchange_order_id(int(payload["orderId"]))
    if intent is None:
        return None
    return journal.record_exchange_order(intent.client_order_id, payload)


@dataclass(frozen=True)
class RecoveryDependencies:
    """Зависимости recovery-слоя без прямого доступа к глобалам исполнителя."""
    journal: Callable[[], OrderJournal | None]
    get_order_by_client_id: Callable[[str, str], Dict[str, Any] | None]
    get_order_list_by_client_id: Callable[[str], Dict[str, Any] | None]
    verify_oco_legs: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
    cancel_oco: Callable[[str, int], None]
    halt: Callable[..., None]
    logger: Callable[[str], None]


def recover_pending_buy_order_ids(
    symbol: str,
    *,
    dependencies: RecoveryDependencies,
) -> List[int]:
    """Вернуть BUY, которые после рестарта ещё требуют контроля или защиты."""
    journal = dependencies.journal()
    if journal is None:
        return []
    recovered: List[int] = []
    # Локальный intent сам по себе не доказывает наличие заявки на бирже.
    # Истиной считается ответ Binance по устойчивому clientOrderId.
    for intent in journal.unresolved_buys(symbol):
        try:
            payload = dependencies.get_order_by_client_id(
                symbol, intent.client_order_id
            )
        except requests.RequestException as exc:
            journal.mark_unknown(intent.client_order_id, exc)
            reason = (
                f"cannot reconcile BUY {intent.client_order_id} "
                f"after restart: {exc}"
            )
            dependencies.halt(
                reason, symbol=symbol, client_order_id=intent.client_order_id
            )
            raise RuntimeError(reason) from exc
        if payload is None:
            if intent.state not in ("PREPARED", "UNKNOWN"):
                reason = (
                    f"exchange lost unresolved BUY {intent.client_order_id} "
                    f"recorded as {intent.state}"
                )
                dependencies.halt(
                    reason, symbol=symbol, client_order_id=intent.client_order_id
                )
                raise RuntimeError(reason)
            dependencies.logger(
                f"[RECOVERY] {symbol} {intent.client_order_id} not found; "
                "safe to retry same ID"
            )
            continue
        updated = journal.record_exchange_order(intent.client_order_id, payload)
        if updated.state in (
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "FILLED",
            "PROTECTION_PENDING",
        ):
            if updated.exchange_order_id is None:
                reason = (
                    f"reconciled BUY {intent.client_order_id} "
                    "has no exchange orderId"
                )
                dependencies.halt(
                    reason, symbol=symbol, client_order_id=intent.client_order_id
                )
                raise RuntimeError(reason)
            recovered.append(updated.exchange_order_id)
            dependencies.logger(
                f"[RECOVERY] {symbol} client={intent.client_order_id} "
                f"order={updated.exchange_order_id} state={updated.state}"
            )
    return list(dict.fromkeys(recovered))


def recover_existing_protection(
    parent_client_order_id: str,
    *,
    dependencies: RecoveryDependencies,
) -> bool:
    """Проверить и восстановить связь BUY → OCO/резервный SELL."""
    journal = dependencies.journal()
    if journal is None:
        return False
    protection = journal.protection_for_parent(parent_client_order_id)
    if protection is None:
        return False
    if protection.state == "PROTECTED":
        return True
    if protection.order_type == "OCO":
        payload = dependencies.get_order_list_by_client_id(
            protection.client_order_id
        )
        if (
            not isinstance(payload, dict)
            or payload.get("listStatusType") not in ("EXEC_STARTED", "ALL_DONE")
        ):
            return False
        order_list_id = payload.get("orderListId")
        try:
            dependencies.verify_oco_legs(protection.symbol, payload)
        except (requests.RequestException, RuntimeError):
            if order_list_id is not None:
                dependencies.cancel_oco(protection.symbol, int(order_list_id))
            return False
        journal.mark_protected(
            parent_client_order_id=parent_client_order_id,
            protection_client_order_id=protection.client_order_id,
            order_list_id=(
                int(order_list_id) if order_list_id is not None else None
            ),
        )
        return True
    payload = dependencies.get_order_by_client_id(
        protection.symbol, protection.client_order_id
    )
    if not isinstance(payload, dict):
        return False
    updated = journal.record_exchange_order(protection.client_order_id, payload)
    if updated.state in ("SUBMITTED", "PARTIALLY_FILLED", "FILLED"):
        journal.mark_protected(
            parent_client_order_id=parent_client_order_id,
            protection_client_order_id=protection.client_order_id,
            exchange_order_id=updated.exchange_order_id,
        )
        return True
    return False


def get_order(
    symbol: str,
    order_id: int,
    *,
    signed_request: Callable[..., Any],
    record_payload: Callable[[Dict[str, Any] | None], Optional[OrderIntent]],
    logger: Callable[[str], None],
) -> Dict[str, Any] | None:
    try:
        payload = signed_request(
            "GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}
        )
        record_payload(payload)
        return payload
    except Exception as exc:
        logger(f"[ERR] get_order: {exc}")
        return None
