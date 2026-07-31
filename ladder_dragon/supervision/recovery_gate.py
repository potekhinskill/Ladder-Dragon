# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reconcile durable startup state through explicit exchange adapters.

"""Fail-closed startup recovery classification and reconciliation."""

import json
import os
import re
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

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
    halt_path = Path(resolved_limits.halt_file)
    try:
        payload = json.loads(halt_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("halt marker root must be an object")
        reasons = payload.get("reasons")
        if (
            not isinstance(reasons, list)
            or not reasons
            or not all(isinstance(item, str) and item for item in reasons)
            or not isinstance(payload.get("halted_at"), str)
            or not payload.get("halted_at")
            or isinstance(payload.get("cooldown_until"), bool)
            or not isinstance(payload.get("cooldown_until"), (int, float))
        ):
            raise TypeError("halt marker schema is invalid")
        if reason in reasons:
            if not sync_manual_halt_state(resolved_limits):
                raise RuntimeError(
                    "existing halt marker could not be mirrored to risk state"
                )
            return
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, TypeError):
        archive = halt_path.with_name(
            f"{halt_path.name}.corrupt-{time.time_ns()}"
        )
        try:
            shutil.copy2(halt_path, archive)
            archive.chmod(0o600)
        except OSError as exc:
            raise RuntimeError(
                "corrupt halt marker could not be archived"
            ) from exc
    except OSError as exc:
        raise RuntimeError("halt marker could not be read") from exc
    create_manual_halt(reason, limits=resolved_limits, metadata=metadata)


def exchange_order_absent(exc: BaseException) -> bool:
    """Return whether Binance definitively reported a missing order."""
    current: BaseException | None = exc
    seen: set[int] = set()
    code_pattern = re.compile(
        r"(?:^|[\s,{])(?:['\"]?code['\"]?)\s*[:=]\s*-2013(?!\d)"
    )
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "code", None)
        if code == -2013 or str(code).strip() == "-2013":
            return True
        text = str(current).lower()
        if code_pattern.search(text) or "order does not exist" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


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


def _halt_recovery(
    create_halt: Any,
    reason: str,
    *,
    gate: str,
    metadata: dict[str, object] | None = None,
    cause: BaseException | None = None,
) -> NoReturn:
    """Persist one startup invariant failure before stopping recovery."""
    create_halt(
        reason,
        metadata={"gate": gate, **(metadata or {})},
    )
    if cause is not None:
        raise RuntimeError(reason) from cause
    raise RuntimeError(reason)


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
        _halt_recovery(
            create_halt,
            "LIVE order journal path is missing",
            gate="startup_missing_order_journal",
        )
    journal = order_journal(
        path,
        venue="testnet" if args.testnet else "mainnet",
    )
    checked = 0
    for intent in journal.nonterminal_orders():
        if intent.symbol not in symbols:
            _halt_recovery(
                create_halt,
                "unresolved journal symbol is outside configuration: "
                f"{intent.symbol}",
                gate="startup_journal_symbol_mismatch",
                metadata={
                    "symbol": intent.symbol,
                    "client_order_id": intent.client_order_id,
                },
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
                _halt_recovery(
                    create_halt,
                    f"exchange cannot find durable {intent.side} order "
                    f"recorded as {intent.state}",
                    gate="startup_missing_durable_order",
                    metadata={
                        "symbol": intent.symbol,
                        "client_order_id": intent.client_order_id,
                        "journal_state": intent.state,
                    },
                    cause=exc,
                )
            journal.mark_failed(
                intent.client_order_id,
                "exchange confirmed order absent during supervisor preflight",
            )
            checked += 1
            continue
        if not isinstance(payload, dict):
            _halt_recovery(
                create_halt,
                "order reconciliation response is invalid",
                gate="startup_invalid_order_response",
                metadata={
                    "symbol": intent.symbol,
                    "client_order_id": intent.client_order_id,
                },
            )
        try:
            journal.record_exchange_order(intent.client_order_id, payload)
        except (KeyError, TypeError, ValueError) as exc:
            _halt_recovery(
                create_halt,
                "exchange order cannot update the durable journal",
                gate="startup_invalid_order_response",
                metadata={
                    "symbol": intent.symbol,
                    "client_order_id": intent.client_order_id,
                },
                cause=exc,
            )
        checked += 1
    for buy in journal.unresolved_buys():
        try:
            executed = finite_decimal(
                buy.executed_qty,
                name="reconciled executed quantity",
            )
        except (TypeError, ValueError) as exc:
            _halt_recovery(
                create_halt,
                "reconciled BUY has an invalid executed quantity",
                gate="startup_invalid_executed_quantity",
                metadata={
                    "symbol": buy.symbol,
                    "client_order_id": buy.client_order_id,
                },
                cause=exc,
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
