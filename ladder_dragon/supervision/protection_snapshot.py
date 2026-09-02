# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reuse one authoritative open-order snapshot for protection checks.

"""Validate reusable Binance protection rows from one open-order snapshot."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence


_REQUIRED_ORDER_FIELDS = frozenset(
    {
        "orderId",
        "orderListId",
        "clientOrderId",
        "symbol",
        "side",
        "type",
        "status",
    }
)


def indexed_open_protection_orders(
    open_orders: Sequence[Mapping[str, object]] | None,
    *,
    symbol: str,
    order_list_id: int,
) -> dict[int, dict[str, object]]:
    """Index complete orders for one protection list or request fallback."""
    if open_orders is None:
        return {}
    indexed: dict[int, dict[str, object]] = {}
    for raw in open_orders:
        if not isinstance(raw, Mapping):
            return {}
        try:
            observed_list_id = int(raw.get("orderListId", -1))
        except (TypeError, ValueError):
            return {}
        if observed_list_id != order_list_id:
            continue
        if not _REQUIRED_ORDER_FIELDS.issubset(raw):
            return {}
        if str(raw.get("symbol") or "").upper() != symbol.upper():
            raise RuntimeError("open protection symbol differs from durable journal")
        try:
            order_id = int(raw["orderId"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("open protection order ID is invalid") from exc
        if order_id in indexed:
            raise RuntimeError("open protection snapshot contains a duplicate order")
        indexed[order_id] = dict(raw)
    return indexed


def select_open_single_protection(
    open_orders: Sequence[Mapping[str, object]] | None,
    *,
    symbol: str,
    order_id: int,
    client_order_id: str,
) -> dict[str, object] | None:
    """Return one complete active protection order or request fallback."""
    if open_orders is None:
        return None
    matches = []
    for raw in open_orders:
        if not isinstance(raw, Mapping):
            return None
        try:
            matches_order = int(raw.get("orderId", -1)) == order_id
        except (TypeError, ValueError):
            return None
        if matches_order:
            matches.append(raw)
    if not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError("open protection snapshot contains a duplicate order")
    observed = matches[0]
    if not _REQUIRED_ORDER_FIELDS.issubset(observed):
        return None
    if str(observed.get("symbol") or "").upper() != symbol.upper():
        raise RuntimeError("open protection symbol differs from durable journal")
    if str(observed.get("clientOrderId") or "") != client_order_id:
        raise RuntimeError("open protection client ID differs from durable journal")
    return dict(observed)


def verify_live_protection(
    journal: Any,
    parent_client_order_id: str,
    *,
    open_orders: Sequence[Mapping[str, object]] | None,
    signed_get: Callable[..., object],
    classify_oco_legs: Callable[..., tuple[str, object, object]],
    now_epoch: Callable[[], int],
) -> int:
    """Verify one protection using an open snapshot and exact fallbacks."""
    protection = journal.protection_for_parent(parent_client_order_id)
    if protection is None:
        raise RuntimeError("protected BUY has no linked protection intent")
    if protection.order_type in {"OCO", "OTOCO"}:
        list_type = protection.order_type
        payload = signed_get(
            "/api/v3/orderList",
            {"origClientOrderId": protection.client_order_id},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("OCO reconciliation response is invalid")
        if (
            str(payload.get("listClientOrderId") or "")
            != protection.client_order_id
            or int(payload.get("orderListId", -1))
            != int(protection.exchange_order_list_id or -2)
            or str(payload.get("contingencyType") or "").upper() != list_type
        ):
            raise RuntimeError(f"{list_type} identity differs from durable journal")
        list_status = str(payload.get("listStatusType") or "").upper()
        if list_status not in {"EXEC_STARTED", "ALL_DONE"}:
            raise RuntimeError(f"{list_type} has an unknown exchange status")
        references = payload.get("orders")
        expected_orders = 3 if list_type == "OTOCO" else 2
        if not isinstance(references, list) or len(references) != expected_orders:
            raise RuntimeError(
                f"{list_type} does not contain exactly {expected_orders} orders"
            )
        # The list read proves current identity and status. The earlier
        # open-order snapshot replaces only exact active-leg reads.
        open_by_id = (
            indexed_open_protection_orders(
                open_orders,
                symbol=protection.symbol,
                order_list_id=int(protection.exchange_order_list_id or -2),
            )
            if list_status == "EXEC_STARTED"
            else {}
        )
        queried: list[dict[str, object]] = []
        for reference in references:
            if not isinstance(reference, dict) or reference.get("orderId") is None:
                raise RuntimeError("OCO leg reference is invalid")
            if str(reference.get("symbol") or "").upper() != protection.symbol:
                raise RuntimeError("OCO leg symbol differs from durable journal")
            order_id = int(reference["orderId"])
            leg = open_by_id.get(order_id) or signed_get(
                "/api/v3/order",
                {"symbol": protection.symbol, "orderId": order_id},
            )
            if not isinstance(leg, dict):
                raise RuntimeError("OCO leg reconciliation response is invalid")
            reference_client_id = str(reference.get("clientOrderId") or "")
            if (
                reference_client_id
                and str(leg.get("clientOrderId") or "")
                != reference_client_id
            ):
                raise RuntimeError("OCO leg client ID differs from order list")
            queried.append(leg)
        if list_type == "OTOCO":
            working = [
                order
                for order in queried
                if str(order.get("clientOrderId") or "")
                == parent_client_order_id
            ]
            if (
                len(working) != 1
                or str(working[0].get("side") or "").upper() != "BUY"
                or str(working[0].get("status") or "").upper() != "FILLED"
            ):
                raise RuntimeError("OTOCO working BUY is not exactly FILLED")
            legs = [
                order
                for order in queried
                if str(order.get("clientOrderId") or "")
                != parent_client_order_id
            ]
        else:
            legs = queried
        if any(str(leg.get("side") or "").upper() != "SELL" for leg in legs):
            raise RuntimeError(f"{list_type} contains a non-SELL protection leg")
        if any(
            str(leg.get("symbol") or "").upper() != protection.symbol
            or int(leg.get("orderListId", -1))
            != int(protection.exchange_order_list_id or -2)
            for leg in legs
        ):
            raise RuntimeError(f"{list_type} leg identity differs from durable journal")
        leg_types = {str(leg.get("type") or "").upper() for leg in legs}
        if not ({"LIMIT_MAKER", "LIMIT"} & leg_types) or not (
            {"STOP_LOSS_LIMIT", "STOP_LOSS"} & leg_types
        ):
            raise RuntimeError(f"{list_type} protection leg types are invalid")
        outcome, filled_leg, exit_reason = classify_oco_legs(legs)
        if list_status == "ALL_DONE" and outcome == "CLOSED":
            if (
                filled_leg is None
                or exit_reason is None
                or filled_leg.get("orderId") is None
            ):
                raise RuntimeError(f"{list_type} closed without an exact SELL fill")
            journal.record_verified_protection_legs(
                protection.client_order_id, legs
            )
            journal.mark_exact_lifecycle_closed(
                protection_client_order_id=protection.client_order_id,
                exit_order_id=int(filled_leg["orderId"]),
                exit_reason=exit_reason,
            )
            return 0
        if list_status != "EXEC_STARTED" or outcome != "ACTIVE":
            raise RuntimeError(f"{list_type} is not actively protecting inventory")
        observed_ids = {int(leg["orderId"]) for leg in legs}
        stored_ids = {
            int(row["order_id"])
            for row in (protection.metadata or {}).get("verified_legs", [])
            if isinstance(row, dict) and row.get("order_id") is not None
        }
        if stored_ids and stored_ids != observed_ids:
            raise RuntimeError(f"{list_type} exchange legs differ from durable journal")
        journal.update_metadata(
            protection.client_order_id,
            {
                "verified_legs": [
                    {
                        "order_id": int(leg["orderId"]),
                        "client_order_id": str(leg.get("clientOrderId") or ""),
                        "leg_type": str(leg.get("type") or "").upper(),
                    }
                    for leg in legs
                ],
                "startup_exchange_verified_at": now_epoch(),
            },
        )
        return 3
    payload = select_open_single_protection(
        open_orders,
        symbol=protection.symbol,
        order_id=int(protection.exchange_order_id or -2),
        client_order_id=protection.client_order_id,
    ) or signed_get(
        "/api/v3/order",
        {
            "symbol": protection.symbol,
            "origClientOrderId": protection.client_order_id,
        },
    )
    if (
        not isinstance(payload, dict)
        or str(payload.get("symbol") or "").upper() != protection.symbol
        or int(payload.get("orderId", -1))
        != int(protection.exchange_order_id or -2)
        or str(payload.get("side") or "").upper() != "SELL"
        or str(payload.get("type") or "").upper()
        != protection.order_type.upper()
        or str(payload.get("status") or "").upper()
        not in {"NEW", "PARTIALLY_FILLED"}
    ):
        raise RuntimeError("single-order protection is not active")
    return 1


def verify_all_live_protection(
    journal: Any,
    symbols: Sequence[str],
    *,
    open_orders: Sequence[Mapping[str, object]] | None,
    verify_one: Callable[[Any, str, Sequence[Mapping[str, object]] | None], int],
) -> int:
    """Verify every configured protected BUY from one open-order snapshot."""
    checked = 0
    configured = {str(symbol).upper() for symbol in symbols}
    for buy in journal.protected_buys():
        if buy.symbol not in configured:
            raise RuntimeError("protected journal symbol is outside configuration")
        checked += verify_one(journal, buy.client_order_id, open_orders)
    return checked


__all__ = [
    "indexed_open_protection_orders",
    "select_open_single_protection",
    "verify_all_live_protection",
    "verify_live_protection",
]
