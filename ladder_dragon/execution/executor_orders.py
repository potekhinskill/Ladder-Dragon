# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor orders component of the execution layer.
"""Идемпотентное размещение LIMIT и OCO для символьного исполнителя."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import requests

from ladder_dragon.execution.binance_transport import BinanceResponseError
from ladder_dragon.execution.order_identity import client_order_id
from ladder_dragon.execution.order_recovery import OrderJournal, TERMINAL_EXCHANGE_STATES


def _record_definitive_rejection(
    journal: OrderJournal | None,
    client_id: str,
    error: BaseException,
    logger: Callable[[str], None],
) -> bool:
    """Record an exchange business rejection without treating it as a lost ACK."""
    if not isinstance(error, BinanceResponseError):
        return False
    if journal is not None:
        journal.mark_failed(client_id, error)
    logger(
        f"[REJECTED] client={client_id} status={error.status} "
        f"code={error.code} endpoint={error.endpoint} "
        f"message={error.binance_message or 'request rejected'}"
    )
    return True


def _link_ai_order(
    client_id: str, symbol: str, *, lot_id: int | None = None,
    order_type: str = "", leg_type: str = "", expected_price: float | None = None,
) -> None:
    """Сохранить связь clientOrderId с decision до сетевого POST."""
    decision_id = os.getenv("BOT_AI_DECISION_ID", "").strip()
    db_path = os.getenv("AI_DECISIONS_DB", "").strip()
    if not decision_id or not db_path:
        return
    try:
        from ladder_dragon.ai.ai_context import AdvisorDecisionStore
        AdvisorDecisionStore(db_path).link_client_order(client_id, decision_id,
                                                        symbol=symbol, lot_id=lot_id,
                                                        order_type=order_type,
                                                        leg_type=leg_type,
                                                        expected_price=expected_price)
    except (OSError, ValueError, sqlite3.Error):
        return


def _update_ai_order(
    client_id: str, *, exchange_order_id: str | int | None = None,
    exchange_order_list_id: str | int | None = None, leg_type: str | None = None,
) -> None:
    """Сохранить подтверждённые Binance IDs для точного fill mapping."""
    decision_id = os.getenv("BOT_AI_DECISION_ID", "").strip()
    db_path = os.getenv("AI_DECISIONS_DB", "").strip()
    if not decision_id or not db_path or not client_id:
        return
    try:
        from ladder_dragon.ai.ai_context import AdvisorDecisionStore
        AdvisorDecisionStore(db_path).update_order_link(
            client_id,
            exchange_order_id=exchange_order_id,
            exchange_order_list_id=exchange_order_list_id,
            leg_type=leg_type,
        )
    except (OSError, ValueError, sqlite3.Error):
        return


def _persist_verified_oco_legs(
    journal: OrderJournal | None,
    protection_client_order_id: str,
    legs: object,
) -> list[dict[str, Any]]:
    """Persist only the two detailed, exchange-verified OCO leg records."""
    detailed = [leg for leg in legs if isinstance(leg, dict)] if isinstance(legs, list) else []
    if len(detailed) != 2:
        raise RuntimeError("OCO verification did not return exactly two detailed legs")
    if journal is not None:
        journal.record_verified_protection_legs(
            protection_client_order_id,
            detailed,
        )
    return detailed


@dataclass(frozen=True)
class OrderDependencies:
    """Поздно связываемые зависимости ордерного слоя.

    Такая граница не даёт модулю напрямую читать глобальные ключи и позволяет
    тестировать размещение с полностью отключённой сетью.
    """
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
    """Разместить LIMIT, сохранив intent до POST и восстановив неопределённый ACK."""
    # Repeat the DRY gate immediately before mutation: a startup check alone
    # is insufficient because mode can change in a long-lived process.
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
    # First find an equivalent active intent. If the order already exists on
    # Binance, return it instead of sending another POST.
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
    _link_ai_order(order_client_id, symbol, order_type="LIMIT", expected_price=price)
    if journal is not None:
        # Commit PREPARED before the network request; this is the idempotency base.
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
        _update_ai_order(order_client_id, exchange_order_id=order_id)
        dependencies.logger(
            f"[PLACE] {symbol} {side} {quantity_text} @ {price_text} "
            f"client={order_client_id} order={order_id}"
        )
        return payload
    except requests.RequestException as exc:
        if _record_definitive_rejection(
            journal, order_client_id, exc, dependencies.logger
        ):
            raise
        # A POST timeout does not prove Binance rejected the order. Reconcile
        # clientOrderId first, then create a persistent halt only if uncertain.
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
                _update_ai_order(
                    order_client_id,
                    exchange_order_id=reconciled.get("orderId")
                    if isinstance(reconciled, dict) else None,
                )
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



def place_market_order(
    symbol: str,
    side: str,
    quantity: float,
    *,
    dependencies: OrderDependencies,
    ref_price: float | None = None,
    filters: Dict[str, Any] | None = None,
    parent_client_order_id: Optional[str] = None,
) -> Dict[str, Any] | None:
    """Place an idempotent MARKET order for emergency or time-stop flattening.

    ``filters`` is accepted for compatibility with callers that already have a
    snapshot; the dependency callbacks remain authoritative and refresh filters
    before a live mutation. A SELL is never rounded up to satisfy minNotional:
    flattening must not oversell the account.
    """
    del filters
    side = side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError(f"unsupported market side: {side}")
    if not dependencies.live():
        dependencies.logger(
            f"[DRY] skip MARKET {symbol} {side} {quantity:.8f}"
        )
        return None

    dependencies.pull_filters(symbol)
    rounded_quantity = dependencies.round_qty(symbol, quantity)
    if rounded_quantity <= 0 or rounded_quantity < dependencies.min_qty(symbol, 0):
        dependencies.logger(
            f"[SKIP] MARKET {symbol} {side}: quantity below exchange minimum"
        )
        return None
    if ref_price is not None and (
        rounded_quantity * ref_price < dependencies.min_notional(symbol, ref_price)
    ):
        dependencies.logger(
            f"[SKIP] MARKET {symbol} {side}: quantity below minNotional"
        )
        return None

    quantity_text = dependencies.format_qty(symbol, rounded_quantity)
    purpose = "market"
    journal = dependencies.journal()
    active = (
        journal.find_active(
            symbol=symbol,
            side=side,
            purpose=purpose,
            quantity=quantity_text,
            price="MARKET",
        )
        if journal is not None
        else None
    )
    if active is not None:
        existing = dependencies.get_order_by_client_id(symbol, active.client_order_id)
        if existing is not None:
            if journal is not None:
                journal.record_exchange_order(active.client_order_id, existing)
            return existing

    generated_id = client_order_id(
        symbol, side, purpose, "MARKET", quantity_text, bucket_seconds=30
    )
    if journal is not None and journal.get(generated_id) is not None:
        generated_id = client_order_id(
            symbol,
            side,
            f"{purpose}-{time.time_ns()}",
            "MARKET",
            quantity_text,
            bucket_seconds=1,
        )
    _link_ai_order(
        generated_id,
        symbol,
        order_type="MARKET",
        expected_price=ref_price,
    )
    if journal is not None:
        journal.prepare(
            client_order_id=generated_id,
            symbol=symbol,
            side=side,
            purpose=purpose,
            order_type="MARKET",
            quantity=quantity_text,
            price="MARKET",
            parent_client_order_id=parent_client_order_id,
        )

    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": quantity_text,
        "newOrderRespType": "RESULT",
        "newClientOrderId": generated_id,
    }
    try:
        payload = dependencies.signed_request("POST", "/api/v3/order", params)
        if not isinstance(payload, dict) or payload.get("orderId") is None:
            raise RuntimeError("MARKET response has no orderId")
        payload.setdefault("clientOrderId", generated_id)
        if journal is not None:
            journal.record_exchange_order(generated_id, payload)
        _update_ai_order(generated_id, exchange_order_id=payload.get("orderId"))
        dependencies.logger(
            f"[PLACE] {symbol} {side} {quantity_text} @ MARKET "
            f"client={generated_id} order={payload.get('orderId')}"
        )
        return payload
    except requests.RequestException as exc:
        if _record_definitive_rejection(
            journal, generated_id, exc, dependencies.logger
        ):
            raise
        if journal is not None:
            journal.mark_unknown(generated_id, exc)
            try:
                reconciled = dependencies.get_order_by_client_id(symbol, generated_id)
            except requests.RequestException:
                reconciled = None
            if reconciled is not None:
                journal.record_exchange_order(generated_id, reconciled)
                _update_ai_order(
                    generated_id, exchange_order_id=reconciled.get("orderId")
                )
                dependencies.logger(
                    f"[IDEMPOTENT] recovered uncertain MARKET "
                    f"client={generated_id}"
                )
                return reconciled
            dependencies.halt(
                f"uncertain MARKET submission has no exchange confirmation: {generated_id}",
                symbol=symbol,
                side=side,
                client_order_id=generated_id,
            )
        dependencies.logger(f"[ERR] MARKET {symbol} {side}: {exc}")
        raise
    except Exception as exc:
        dependencies.logger(f"[ERR] MARKET {symbol} {side}: {exc}")
        return None

def place_oco_sell(
    symbol: str,
    quantity: float,
    tp_limit_price: float,
    sl_stop_price: float,
    sl_limit_price: float,
    *,
    dependencies: OrderDependencies,
    parent_client_order_id: Optional[str] = None,
    lot_id: int | None = None,
) -> Dict[str, Any] | None:
    """Создать и обязательно проверить обе защитные ноги SELL OCO."""
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
    # Protection is tied to the parent BUY: after restart the same OCO is found
    # by listClientOrderId and reused.
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
    _link_ai_order(list_client_id, symbol, lot_id=lot_id, order_type="OCO", leg_type="LIST",
                   expected_price=float(tp_text))
    if active is not None:
        existing = dependencies.get_order_list_by_client_id(list_client_id)
        if (
            isinstance(existing, dict)
            and existing.get("listStatusType") in ("EXEC_STARTED", "ALL_DONE")
        ):
            order_list_id = existing.get("orderListId")
            try:
                verified_legs = dependencies.verify_oco_legs(symbol, existing)
            except (requests.RequestException, RuntimeError):
                if order_list_id is not None:
                    dependencies.cancel_oco(symbol, int(order_list_id))
                raise
            if journal is not None:
                journal.record_order_list(list_client_id, existing)
                _persist_verified_oco_legs(journal, list_client_id, verified_legs)
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
            _update_ai_order(
                list_client_id,
                exchange_order_list_id=order_list_id,
                leg_type="LIST",
            )
            for leg in verified_legs:
                if isinstance(leg, dict) and leg.get("clientOrderId"):
                    _link_ai_order(
                        str(leg["clientOrderId"]), symbol, lot_id=lot_id,
                        order_type="OCO_LEG", leg_type=str(leg.get("type", "")),
                        expected_price=float(leg.get("price") or leg.get("stopPrice") or 0),
                    )
                    _update_ai_order(
                        str(leg["clientOrderId"]),
                        exchange_order_id=leg.get("orderId"),
                        exchange_order_list_id=order_list_id,
                        leg_type=str(leg.get("type", "")),
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
                "lot_id": lot_id,
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
        # A successful POST response is insufficient: reread the list and each leg.
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
            verified_legs = dependencies.verify_oco_legs(symbol, verified)
        except (requests.RequestException, RuntimeError):
            # Partial or malformed protection is worse than no protection:
            # delete the suspect OCO and propagate the error.
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
        _update_ai_order(
            list_client_id,
            exchange_order_list_id=order_list_id,
            leg_type="LIST",
        )
        for leg in verified_legs:
            if not isinstance(leg, dict):
                continue
            leg_client_id = leg.get("clientOrderId")
            leg_order_id = leg.get("orderId")
            if leg_client_id:
                _link_ai_order(
                    str(leg_client_id), symbol, lot_id=lot_id,
                    order_type="OCO_LEG", leg_type=str(leg.get("type", "")),
                    expected_price=float(leg.get("price") or leg.get("stopPrice") or 0),
                )
                _update_ai_order(
                    str(leg_client_id), exchange_order_id=leg_order_id,
                    exchange_order_list_id=order_list_id,
                    leg_type=str(leg.get("type", "")),
                )
        if journal is not None:
            journal.record_order_list(list_client_id, verified)
            _persist_verified_oco_legs(journal, list_client_id, verified_legs)
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
        if _record_definitive_rejection(
            journal, list_client_id, exc, dependencies.logger
        ):
            if journal is not None and parent_client_order_id:
                journal.mark_protection_pending(parent_client_order_id)
            return None
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
                    verified_legs = dependencies.verify_oco_legs(symbol, reconciled)
                except (requests.RequestException, RuntimeError) as verify_exc:
                    dependencies.logger(
                        f"[ERR] recovered OCO leg verification failed: "
                        f"{verify_exc}"
                    )
                    return None
                journal.record_order_list(list_client_id, reconciled)
                _persist_verified_oco_legs(journal, list_client_id, verified_legs)
                _update_ai_order(
                    list_client_id,
                    exchange_order_list_id=order_list_id,
                    leg_type="LIST",
                )
                for leg in verified_legs:
                    if isinstance(leg, dict) and leg.get("clientOrderId"):
                        _link_ai_order(
                            str(leg["clientOrderId"]), symbol, lot_id=lot_id,
                            order_type="OCO_LEG", leg_type=str(leg.get("type", "")),
                            expected_price=float(leg.get("price") or leg.get("stopPrice") or 0),
                        )
                        _update_ai_order(
                            str(leg["clientOrderId"]),
                            exchange_order_id=leg.get("orderId"),
                            exchange_order_list_id=order_list_id,
                            leg_type=str(leg.get("type", "")),
                        )
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
