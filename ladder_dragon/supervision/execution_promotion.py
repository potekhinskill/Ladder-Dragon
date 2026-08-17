# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep staged symbol promotion outside execution until every gate passes.
"""Build a fail-closed execution-promotion report for SHADOW symbols."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import sqlite3
from typing import Mapping, Sequence

from ladder_dragon.strategy.prediction.experiment_config import (
    experiment_spec_for_symbol,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    list_experiments,
)


_SYMBOL_RE = re.compile(r"[A-Z0-9]{5,20}")
_REVIEWED_BASELINE_EXECUTION_SYMBOLS = frozenset({"SOLUSDT"})


def resolve_execution_candidate_symbols(configured: str) -> list[str]:
    """Parse the staged symbol list without changing execution scope."""
    symbols = [
        item.strip().upper()
        for item in configured.split(",")
        if item.strip()
    ]
    if len(symbols) != len(set(symbols)):
        raise ValueError("BOT_EXECUTION_CANDIDATE_SYMBOLS contains duplicates")
    for symbol in symbols:
        if _SYMBOL_RE.fullmatch(symbol) is None:
            raise ValueError(
                "invalid BOT_EXECUTION_CANDIDATE_SYMBOLS symbol: "
                f"{symbol!r}"
            )
    return symbols


def _positive_cap(
    environment: Mapping[str, str], name: str
) -> tuple[Decimal | None, str | None]:
    raw = environment.get(name)
    if raw is None or not raw.strip():
        return None, f"{name} is not configured"
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        return None, f"{name} is invalid"
    if not value.is_finite() or value <= 0:
        return None, f"{name} must be positive"
    return value, None


def _current_generation_status(store: object, symbol: str) -> tuple[str, str]:
    generation = experiment_spec_for_symbol(symbol).generation
    manifests = [
        row
        for row in list_experiments(store, symbol=symbol)
        if str(row.get("generation") or "") == generation
    ]
    if not manifests:
        return generation, "SELECTION"
    manifests.sort(
        key=lambda row: (
            int(row.get("created_at_ms") or 0),
            str(row.get("experiment_id") or ""),
        )
    )
    return generation, str(manifests[-1].get("current_status") or "BLOCKED")


def build_execution_promotion_report(
    *,
    execution_symbols: Sequence[str],
    prediction_symbols: Sequence[str],
    candidate_symbols: Sequence[str],
    store: object | None,
    environment: Mapping[str, str],
) -> dict[str, object]:
    """Report promotion gates and reject premature execution scope changes."""
    execution = {item.strip().upper() for item in execution_symbols}
    prediction = {item.strip().upper() for item in prediction_symbols}
    candidates: dict[str, object] = {}
    blocked_execution: list[str] = []

    for symbol in candidate_symbols:
        blockers: list[str] = []
        try:
            generation, lifecycle = (
                _current_generation_status(store, symbol)
                if store is not None
                else (experiment_spec_for_symbol(symbol).generation, "UNAVAILABLE")
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            sqlite3.Error,
            TypeError,
            ValueError,
        ) as exc:
            generation = "UNKNOWN"
            lifecycle = "UNAVAILABLE"
            blockers.append(
                f"experiment lifecycle unavailable: {type(exc).__name__}"
            )

        order_cap_name = f"RISK_SYMBOL_CAP_{symbol}"
        inventory_cap_name = f"RISK_MANAGED_INVENTORY_HARD_CAP_{symbol}"
        order_cap, order_cap_error = _positive_cap(environment, order_cap_name)
        inventory_cap, inventory_cap_error = _positive_cap(
            environment, inventory_cap_name
        )
        approval_name = f"BOT_EXECUTION_PROMOTION_APPROVED_{symbol}"
        approved = environment.get(approval_name, "").strip().upper() == "YES"

        if symbol not in prediction:
            blockers.append("symbol is outside prediction SHADOW scope")
        if lifecycle != "CONFIRMED":
            blockers.append(f"experiment lifecycle is {lifecycle}, not CONFIRMED")
        if order_cap_error:
            blockers.append(order_cap_error)
        if inventory_cap_error:
            blockers.append(inventory_cap_error)
        if (
            order_cap is not None
            and inventory_cap is not None
            and order_cap > inventory_cap
        ):
            blockers.append("per-order CAP exceeds managed-inventory hard CAP")
        if not approved:
            blockers.append(f"{approval_name}=YES is required")

        eligible = not blockers
        enabled = symbol in execution
        if enabled and not eligible:
            blocked_execution.append(symbol)
        candidates[symbol] = {
            "generation": generation,
            "lifecycle_status": lifecycle,
            "prediction_shadow": symbol in prediction,
            "operator_approved": approved,
            "order_cap_usdt": (
                format(order_cap, "f") if order_cap is not None else None
            ),
            "managed_inventory_hard_cap_usdt": (
                format(inventory_cap, "f")
                if inventory_cap is not None
                else None
            ),
            "promotion_eligible": eligible,
            "execution_enabled": enabled,
            "blocking_reasons": blockers,
        }

    return {
        "schema_version": 1,
        "mode": "STAGED",
        "can_change_execution_scope": False,
        "lookahead": False,
        "candidate_symbols": list(candidate_symbols),
        "blocked_execution_symbols": blocked_execution,
        "candidates": candidates,
    }


def require_safe_execution_scope(report: Mapping[str, object]) -> None:
    """Stop startup when a staged symbol enters execution before approval."""
    blocked = report.get("blocked_execution_symbols")
    if isinstance(blocked, list) and blocked:
        symbols = ",".join(str(item) for item in blocked)
        raise ValueError(
            "execution promotion is blocked for staged symbols: " + symbols
        )


def prepare_execution_promotion_report(
    *,
    execution_symbols: Sequence[str],
    prediction_symbols: Sequence[str],
    store: object | None,
    environment: Mapping[str, str],
) -> dict[str, object]:
    """Resolve candidates, build their report, and enforce startup safety."""
    candidates = resolve_execution_candidate_symbols(
        environment.get(
            "BOT_EXECUTION_CANDIDATE_SYMBOLS",
            "BTCUSDT,ETHUSDT",
        )
    )
    new_execution = (
        symbol.strip().upper()
        for symbol in execution_symbols
        if symbol.strip().upper() not in _REVIEWED_BASELINE_EXECUTION_SYMBOLS
    )
    candidates = list(dict.fromkeys([*candidates, *new_execution]))
    report = build_execution_promotion_report(
        execution_symbols=execution_symbols,
        prediction_symbols=prediction_symbols,
        candidate_symbols=candidates,
        store=store,
        environment=environment,
    )
    require_safe_execution_scope(report)
    return report


__all__ = [
    "build_execution_promotion_report",
    "prepare_execution_promotion_report",
    "require_safe_execution_scope",
    "resolve_execution_candidate_symbols",
]
