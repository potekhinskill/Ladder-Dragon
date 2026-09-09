# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor recovery component of the execution layer.
"""Ladder Dragon executor recovery support."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

import requests
from ladder_dragon.execution.exchange_evidence import checked_order, checked_list, checked_references
from ladder_dragon.execution.open_order_snapshot import checked_open_orders
from ladder_dragon.execution.protection_quantity import verify_quantities

from ladder_dragon.execution.order_recovery import (
    OrderIntent,
    OrderJournal,
    TERMINAL_EXCHANGE_STATES,
)

ACTIVE_PROTECTION_STATES = {"NEW", "PARTIALLY_FILLED"}
TERMINAL_PROTECTION_STATES = {
    "CANCELED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
    "FILLED",
    "REJECTED",
}


def classify_oco_legs(
    legs: List[Dict[str, Any]],
) -> tuple[str, Dict[str, Any] | None, str | None]:
    """Classify an exact two-leg SELL OCO without treating canceled legs as live."""
    if len(legs) != 2 or any(not isinstance(leg, dict) for leg in legs):
        raise RuntimeError("OCO classification requires exactly two legs")
    if any(str(leg.get("side") or "").upper() != "SELL" for leg in legs):
        raise RuntimeError("OCO classification requires SELL legs")
    leg_types = {str(leg.get("type") or "").upper() for leg in legs}
    if not ({"LIMIT_MAKER", "LIMIT"} & leg_types) or not any(
        "STOP" in value for value in leg_types
    ):
        raise RuntimeError("OCO TP/STOP identities are invalid")
    statuses = [str(leg.get("status") or "").upper() for leg in legs]
    quantities: list[Decimal] = []
    for leg in legs:
        try:
            quantity = Decimal(str(leg.get("executedQty") or "0"))
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise RuntimeError("OCO executed quantity is invalid") from exc
        if not quantity.is_finite() or quantity < 0:
            raise RuntimeError("OCO executed quantity is invalid")
        quantities.append(quantity)
    if all(status in ACTIVE_PROTECTION_STATES for status in statuses):
        return "ACTIVE", None, None
    executed_terminal = [
        leg
        for leg, status, quantity in zip(legs, statuses, quantities)
        if status in TERMINAL_PROTECTION_STATES and quantity > 0
    ]
    if (
        len(executed_terminal) == 1
        and all(status in TERMINAL_PROTECTION_STATES for status in statuses)
    ):
        exit_type = str(executed_terminal[0].get("type") or "").upper()
        reason = "STOP" if "STOP" in exit_type else "TP"
        return "CLOSED", executed_terminal[0], reason
    if (
        not any(quantity > 0 for quantity in quantities)
        and all(status in TERMINAL_PROTECTION_STATES for status in statuses)
    ):
        return "CANCELED", None, None
    raise RuntimeError("OCO terminal state is ambiguous")


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
    orders = signed_request("GET", "/api/v3/openOrders", {"symbol": symbol})
    return checked_open_orders(orders, symbol=symbol)


def cancel_order(
    symbol: str,
    order_id: int,
    *,
    signed_request: Callable[..., Any],
    logger: Callable[[str], None],
) -> None:
    signed_request(
        "DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}
    )
    logger(f"[CANCEL] {symbol} order {order_id}")


def cancel_oco(
    symbol: str,
    order_list_id: int,
    *,
    signed_request: Callable[..., Any],
    logger: Callable[[str], None],
) -> None:
    signed_request(
        "DELETE",
        "/api/v3/orderList",
        {"symbol": symbol, "orderListId": int(order_list_id)},
    )
    logger(f"[CANCEL-OCO] {symbol} orderListId={order_list_id}")


def get_order_by_client_id(
    symbol: str,
    client_id: str,
    *,
    signed_request: Callable[..., Any],
) -> Dict[str, Any] | None:
    try:
        payload = signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "origClientOrderId": client_id},
        )
        return checked_order(payload, symbol, client_id=client_id)
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
        payload = signed_request(
            "GET", "/api/v3/orderList", {"origClientOrderId": client_id}
        )
        return checked_list(payload, client_id=client_id)
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
    """Handle verify oco legs."""
    checked_list(order_list, symbol=symbol, kind="OCO")
    refs = checked_references(order_list, symbol, 2)
    legs: List[Dict[str, Any]] = []
    for ref in refs:
        if ref.get("orderId") is None:
            raise RuntimeError("OCO leg has no orderId")
        payload = signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "orderId": int(ref["orderId"])},
        )
        legs.append(checked_order(payload, symbol, order_id=ref["orderId"],
                                  client_id=ref["clientOrderId"], list_id=order_list["orderListId"]))
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
    """Represent RecoveryDependencies."""
    journal: Callable[[], OrderJournal | None]
    get_order_by_client_id: Callable[[str, str], Dict[str, Any] | None]
    get_order_list_by_client_id: Callable[[str], Dict[str, Any] | None]
    verify_oco_legs: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
    cancel_oco: Callable[[str, int], None]
    halt: Callable[..., None]
    logger: Callable[[str], None]


def reconcile_nonterminal_orders(
    symbol: str,
    *,
    dependencies: RecoveryDependencies,
) -> List[OrderIntent]:
    """Reconcile every ordinary intent before a LIVE worker may place orders.

    Binance is authoritative. An UNKNOWN/PREPARED intent that Binance confirms
    as absent never existed and is terminally failed. Losing an order that was
    previously confirmed as submitted is ambiguous and therefore halts LIVE.
    """
    journal = dependencies.journal()
    if journal is None:
        return []
    reconciled: List[OrderIntent] = []
    for intent in journal.nonterminal_orders(symbol):
        try:
            payload = dependencies.get_order_by_client_id(
                intent.symbol, intent.client_order_id
            )
        except requests.RequestException as exc:
            journal.mark_unknown(intent.client_order_id, exc)
            reason = (
                f"cannot reconcile {intent.side} {intent.client_order_id} "
                f"before LIVE execution: {type(exc).__name__}"
            )
            dependencies.halt(
                reason,
                symbol=intent.symbol,
                client_order_id=intent.client_order_id,
            )
            raise RuntimeError(reason) from exc
        if payload is None:
            if intent.state in ("PREPARED", "UNKNOWN"):
                updated = journal.mark_failed(
                    intent.client_order_id,
                    "exchange confirmed order absent during startup reconciliation",
                )
                reconciled.append(updated)
                dependencies.logger(
                    f"[RECOVERY] {intent.symbol} {intent.side} "
                    f"client={intent.client_order_id} absent; state=FAILED"
                )
                continue
            reason = (
                f"exchange lost {intent.side} {intent.client_order_id} "
                f"recorded as {intent.state}"
            )
            dependencies.halt(
                reason,
                symbol=intent.symbol,
                client_order_id=intent.client_order_id,
            )
            raise RuntimeError(reason)
        updated = journal.record_exchange_order(intent.client_order_id, payload)
        reconciled.append(updated)
        dependencies.logger(
            f"[RECOVERY] {intent.symbol} {intent.side} "
            f"client={intent.client_order_id} state={updated.state}"
        )
    return reconciled


def recover_pending_buy_order_ids(
    symbol: str,
    *,
    dependencies: RecoveryDependencies,
) -> List[int]:
    """Recover pending buy order ids."""
    journal = dependencies.journal()
    if journal is None:
        return []
    recovered: List[int] = []
    # A local intent alone does not prove that an exchange order exists.
    # The Binance response for the stable clientOrderId is authoritative.
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
    """Recover existing protection."""
    journal = dependencies.journal()
    if journal is None:
        return False
    protection = journal.protection_for_parent(parent_client_order_id)
    if protection is None:
        return False
    if protection.order_type == "OTOCO":
        payload: Dict[str, Any] | None = None
        order_list_id = None
        try:
            payload = dependencies.get_order_list_by_client_id(
                protection.client_order_id
            )
            checked_list(payload, client_id=protection.client_order_id,
                         list_id=protection.exchange_order_list_id, symbol=protection.symbol, kind="OTOCO")
            order_list_id = (
                payload.get("orderListId")
                if isinstance(payload, dict)
                else None
            )
            refs = checked_references(payload, protection.symbol, 3)
            working = dependencies.get_order_by_client_id(
                protection.symbol,
                parent_client_order_id,
            )
            checked_order(working, protection.symbol, client_id=parent_client_order_id,
                          list_id=order_list_id)
            working_refs = [ref for ref in refs if ref["clientOrderId"] == parent_client_order_id]
            if len(working_refs) != 1 or working_refs[0]["orderId"] != working["orderId"]:
                raise RuntimeError("OTOCO working reference differs from response")
            working_status = str(working.get("status") or "").upper()
            pending: List[Dict[str, Any]] = []
            for ref in refs:
                client_id = str(
                    ref.get("clientOrderId") or ""
                ) if isinstance(ref, dict) else ""
                if not client_id or client_id == parent_client_order_id:
                    continue
                order = dependencies.get_order_by_client_id(
                    protection.symbol,
                    client_id,
                )
                checked_order(order, protection.symbol, client_id=client_id,
                              order_id=ref["orderId"], list_id=order_list_id)
                pending.append(order)
            if len(pending) != 2:
                raise RuntimeError("OTOCO protection pair is incomplete")
            if working_status != "FILLED":
                executed = Decimal(str(working.get("executedQty") or "0"))
                pending_terminal = all(
                    str(order.get("status") or "").upper()
                    in {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"}
                    for order in pending
                )
                if (
                    working_status in TERMINAL_EXCHANGE_STATES
                    and executed > 0
                    and str(payload.get("listStatusType") or "").upper()
                    == "ALL_DONE"
                    and pending_terminal
                ):
                    # The OTOCO list was atomically cancelled after a partial
                    # fill. The caller may now attach an OCO for only the
                    # executed quantity.
                    journal.record_order_list(
                        protection.client_order_id,
                        payload,
                    )
                    return False
                return False
            outcome, filled_leg, exit_reason = classify_oco_legs(pending)
            list_status = str(payload.get("listStatusType") or "").upper()
        except requests.RequestException as exc:
            # Read uncertainty is never permission to remove exchange-side
            # protection. Preserve the list and let the caller halt.
            raise RuntimeError(
                "OTOCO protection verification is unavailable; "
                "existing list was left unchanged"
            ) from exc
        except RuntimeError as exc:
            raise RuntimeError("OTOCO evidence is invalid; existing protection was left unchanged") from exc
        verify_quantities(journal, parent_client_order_id, protection, pending,
                          closing=outcome == "CLOSED" and filled_leg.get("status") == "FILLED")
        if list_status == "ALL_DONE" and outcome == "CLOSED":
            if (
                filled_leg is None
                or exit_reason is None
                or filled_leg.get("orderId") is None
            ):
                raise RuntimeError("closed OTOCO lacks an executed SELL leg")
            journal.record_verified_protection_legs(
                protection.client_order_id,
                pending,
            )
            filled_status = str(filled_leg.get("status") or "").upper()
            if filled_status == "FILLED":
                journal.mark_exact_lifecycle_closed(
                    protection_client_order_id=protection.client_order_id,
                    exit_order_id=int(filled_leg["orderId"]),
                    exit_reason=exit_reason,
                    exit_order=filled_leg,
                )
                return True
            journal.record_partial_protection_exit(
                protection_client_order_id=protection.client_order_id,
                exit_order_id=int(filled_leg["orderId"]),
                exit_reason=exit_reason,
                executed_qty=filled_leg.get("executedQty"),
                terminal_status=filled_status,
            )
            return False
        if list_status == "ALL_DONE" and outcome == "CANCELED":
            journal.mark_failed(
                protection.client_order_id,
                "exchange OTOCO ended without a SELL fill",
            )
            journal.mark_protection_pending(parent_client_order_id)
            return False
        if list_status != "EXEC_STARTED" or outcome != "ACTIVE":
            return False
        journal.mark_verified_protected(
            parent_client_order_id=parent_client_order_id,
            protection_client_order_id=protection.client_order_id,
            legs=pending,
            order_list_id=(
                int(order_list_id) if order_list_id is not None else None
            ),
        )
        return True
    if protection.order_type == "OCO":
        payload: Dict[str, Any] | None = None
        order_list_id = None
        try:
            payload = dependencies.get_order_list_by_client_id(
                protection.client_order_id
            )
            checked_list(payload, client_id=protection.client_order_id,
                         list_id=protection.exchange_order_list_id, symbol=protection.symbol, kind="OCO")
            order_list_id = payload.get("orderListId")
            legs = dependencies.verify_oco_legs(protection.symbol, payload)
            outcome, filled_leg, exit_reason = classify_oco_legs(legs)
        except requests.RequestException as exc:
            raise RuntimeError(
                "OCO protection verification is unavailable; "
                "existing list was left unchanged"
            ) from exc
        except RuntimeError as exc:
            raise RuntimeError("OCO evidence is invalid; existing protection was left unchanged") from exc
        verify_quantities(journal, parent_client_order_id, protection, legs,
                          closing=outcome == "CLOSED" and filled_leg.get("status") == "FILLED")
        list_status = str(payload.get("listStatusType") or "").upper()
        if list_status == "ALL_DONE" and outcome == "CLOSED":
            if (
                filled_leg is None
                or exit_reason is None
                or filled_leg.get("orderId") is None
            ):
                raise RuntimeError("closed OCO lacks an exact filled SELL leg")
            journal.record_verified_protection_legs(
                protection.client_order_id,
                legs,
            )
            filled_status = str(filled_leg.get("status") or "").upper()
            if filled_status == "FILLED":
                journal.mark_exact_lifecycle_closed(
                    protection_client_order_id=protection.client_order_id,
                    exit_order_id=int(filled_leg["orderId"]),
                    exit_reason=exit_reason,
                    exit_order=filled_leg,
                )
                return True
            journal.record_partial_protection_exit(
                protection_client_order_id=protection.client_order_id,
                exit_order_id=int(filled_leg["orderId"]),
                exit_reason=exit_reason,
                executed_qty=filled_leg.get("executedQty"),
                terminal_status=filled_status,
            )
            return False
        if list_status == "ALL_DONE" and outcome == "CANCELED":
            journal.mark_failed(
                protection.client_order_id,
                "exchange OCO ended without a SELL fill",
            )
            journal.mark_protection_pending(parent_client_order_id)
            return False
        if list_status != "EXEC_STARTED" or outcome != "ACTIVE":
            return False
        journal.mark_verified_protected(
            parent_client_order_id=parent_client_order_id,
            protection_client_order_id=protection.client_order_id,
            legs=legs,
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
    checked_order(payload, protection.symbol, order_id=protection.exchange_order_id,
                  client_id=protection.client_order_id)
    if (protection.side != "SELL" or payload.get("side") != "SELL"
            or protection.order_type not in {"STOP_LOSS", "STOP_LOSS_LIMIT"}
            or payload.get("type") != protection.order_type):
        raise RuntimeError("single protection side or type differs from durable STOP intent")
    verify_quantities(journal, parent_client_order_id, protection, [payload])
    if (payload.get("status") not in {"NEW", "PARTIALLY_FILLED"}
            and Decimal(payload["executedQty"]) > 0):
        raise RuntimeError("terminal single protection requires residual reconciliation")
    updated = journal.record_exchange_order(protection.client_order_id, payload)
    if updated.state in ("SUBMITTED", "PARTIALLY_FILLED"):
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
    payload = signed_request(
        "GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}
    )
    checked_order(payload, symbol, order_id=order_id)
    record_payload(payload)
    return payload
