# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reconcile durable startup state through explicit exchange adapters.

"""Fail-closed startup recovery classification and reconciliation."""

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import requests

from ladder_dragon.risk.risk_manager import (
    RiskLimits,
    create_manual_halt,
    sync_manual_halt_state,
)


def create_manual_halt_once(
    reason: str,
    *,
    limits: RiskLimits | None = None,
    metadata: dict[str, object],
) -> None:
    """Persist one safety reason and repair its telemetry without repeat alerts."""
    resolved_limits = limits or RiskLimits.from_env()
    try:
        payload = json.loads(
            Path(resolved_limits.halt_file).read_text(encoding="utf-8")
        )
        if reason in list(payload.get("reasons") or []):
            if not sync_manual_halt_state(resolved_limits):
                raise RuntimeError(
                    "existing halt marker could not be mirrored to risk state"
                )
            return
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        pass
    create_manual_halt(reason, limits=resolved_limits, metadata=metadata)


def exchange_order_absent(exc: BaseException) -> bool:
    """Return whether Binance definitively reported a missing order."""
    text = str(exc).lower()
    return (
        "code=-2013" in text
        or "'code': -2013" in text
        or '"code": -2013' in text
        or "order does not exist" in text
    )


def bounded_recovery_reason(exc: BaseException) -> str:
    """Return one bounded recovery reason without signed URL material."""
    text = str(exc).strip() or type(exc).__name__
    text = re.sub(
        r"(signature=)[^&\s;]+",
        r"\1<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"https://(?:api|testnet)\.binance\.[^\s?]+\?[^\s]+",
        "https://<redacted>",
        text,
        flags=re.IGNORECASE,
    )
    return text[:240]


def _runtime_dependency(runtime: Mapping[str, object], name: str) -> Any:
    """Resolve one explicit runtime adapter used by startup recovery."""
    try:
        return runtime[name]
    except KeyError as exc:
        raise RuntimeError(
            f"recovery runtime dependency is unavailable: {name}"
        ) from exc


def pre_running_recovery_gate(
    args: Any,
    symbols: Sequence[str],
    *,
    runtime: Mapping[str, object],
) -> dict[str, Any]:
    """Reconcile durable intents before the supervisor reports RUNNING."""
    if not args.live:
        return {"checked": 0, "blocked": False}
    order_journal = _runtime_dependency(runtime, "OrderJournal")
    tools_market = _runtime_dependency(runtime, "TM")
    operation_errors = _runtime_dependency(
        runtime, "SUPERVISOR_OPERATION_ERRORS"
    )
    finite_decimal = _runtime_dependency(runtime, "_finite_decimal")
    create_halt = _runtime_dependency(runtime, "_create_manual_halt_once")
    verify_protection = _runtime_dependency(
        runtime, "_verify_all_live_protection"
    )
    absent = _runtime_dependency(runtime, "_exchange_order_absent")

    path = os.getenv("BOT_ORDER_JOURNAL", "").strip()
    if not path:
        raise RuntimeError("LIVE order journal path is missing")
    journal = order_journal(
        path,
        venue="testnet" if args.testnet else "mainnet",
    )
    checked = 0
    for intent in journal.nonterminal_orders():
        if intent.symbol not in symbols:
            raise RuntimeError(
                "unresolved journal symbol is outside configuration: "
                f"{intent.symbol}"
            )
        try:
            payload = tools_market._signed_get(
                "/api/v3/order",
                {
                    "symbol": intent.symbol,
                    "origClientOrderId": intent.client_order_id,
                },
            )
        except operation_errors as exc:
            if not absent(exc):
                raise RuntimeError(
                    "authenticated order reconciliation failed"
                ) from exc
            if intent.state not in {"PREPARED", "UNKNOWN"}:
                raise RuntimeError(
                    f"exchange cannot find durable {intent.side} order "
                    f"recorded as {intent.state}"
                ) from exc
            journal.mark_failed(
                intent.client_order_id,
                "exchange confirmed order absent during supervisor preflight",
            )
            checked += 1
            continue
        if not isinstance(payload, dict):
            raise RuntimeError("order reconciliation response is invalid")
        journal.record_exchange_order(intent.client_order_id, payload)
        checked += 1
    for buy in journal.unresolved_buys():
        executed = finite_decimal(
            buy.executed_qty,
            name="reconciled executed quantity",
        )
        if executed <= 0:
            continue
        protection = journal.protection_for_parent(buy.client_order_id)
        if protection is None or protection.state not in {
            "PROTECTED",
            "CLOSED",
        }:
            order_id = (
                str(buy.exchange_order_id)
                if buy.exchange_order_id is not None
                else "unknown"
            )
            reason = (
                f"reconciled BUY {buy.client_order_id} order={order_id} "
                f"executed={executed} has execution without verified "
                "protection"
            )
            create_halt(
                reason,
                metadata={
                    "gate": "startup_unprotected_fill",
                    "symbol": buy.symbol,
                    "client_order_id": buy.client_order_id,
                    "exchange_order_id": buy.exchange_order_id,
                },
            )
            raise RuntimeError(reason)
    try:
        protection_checks = verify_protection(journal, list(symbols))
    except (
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        requests.RequestException,
    ) as exc:
        reason = f"startup journal protected BUY differs from Binance: {exc}"
        create_halt(
            reason,
            metadata={"gate": "startup_journal_exchange_protection"},
        )
        raise RuntimeError(reason) from exc
    return {
        "checked": checked,
        "protection_checks": protection_checks,
        "blocked": False,
    }
