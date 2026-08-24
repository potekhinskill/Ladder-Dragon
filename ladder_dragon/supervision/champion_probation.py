# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce durable first-live CHAMPION probation limits.
"""Fail-closed CHAMPION probation accounting."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Mapping

from ladder_dragon.risk.risk_manager import RiskDecision


TERMINAL_BUY_STATES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "CLOSED"}


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(f"CHAMPION probation {field} is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise RuntimeError(f"CHAMPION probation {field} is invalid")
    return parsed


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _intent_totals(
    journal_path: Path, *, activation_id: str, symbol: str
) -> tuple[int, int, int, Decimal]:
    if not journal_path.is_file():
        raise RuntimeError("CHAMPION probation order journal is unavailable")
    try:
        with sqlite3.connect(
            f"file:{journal_path}?mode=ro", uri=True, timeout=2
        ) as connection:
            closed_parents = {
                str(row[0]) for row in connection.execute(
                    "SELECT parent_client_order_id FROM order_lifecycle_closures "
                    "WHERE symbol=?",
                    (symbol,),
                )
            }
            rows = connection.execute(
                "SELECT client_order_id,state,quantity,price,metadata_json "
                "FROM order_intents "
                "WHERE symbol=? AND side='BUY'",
                (symbol,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError("CHAMPION probation order journal is unreadable") from exc
    entries = terminals = closed_lifecycles = 0
    turnover = Decimal("0")
    for client_order_id, state, quantity, price, metadata_json in rows:
        try:
            metadata = json.loads(str(metadata_json or "{}"))
            champion = metadata.get("champion")
            if (
                not isinstance(champion, Mapping)
                or champion.get("activation_id") != activation_id
            ):
                continue
            exact_quantity = _decimal(quantity, field="quantity")
            exact_price = _decimal(price, field="price")
        except (json.JSONDecodeError, TypeError, RuntimeError) as exc:
            raise RuntimeError("CHAMPION probation intent is invalid") from exc
        entries += 1
        turnover += exact_quantity * exact_price
        terminals += str(state).upper() in TERMINAL_BUY_STATES
        closed_lifecycles += str(client_order_id) in closed_parents
    return entries, terminals, closed_lifecycles, turnover


def evaluate_champion_probation(
    champions: Mapping[str, Mapping[str, object]],
    *,
    journal_path: Path,
    state_path: Path,
    equity_usdt: Decimal,
    now_ms: int,
    paused: bool = False,
) -> dict[str, object]:
    """Evaluate immutable probation limits and preserve the equity baseline."""
    if not champions:
        return {"status": "NOT_APPLICABLE", "buy_blocked": False}
    if len(champions) != 1:
        return {
            "status": "BLOCKED",
            "buy_blocked": True,
            "halt_reason": "CHAMPION probation supports one execution symbol",
        }
    symbol, champion = next(iter(champions.items()))
    policy = champion.get("execution_policy")
    probation = policy.get("probation") if isinstance(policy, Mapping) else None
    if not isinstance(probation, Mapping):
        return {
            "status": "BLOCKED",
            "buy_blocked": True,
            "halt_reason": "CHAMPION probation policy is unavailable",
        }
    activation_id = str(champion.get("activation_id") or "")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise TypeError("probation state root is invalid")
    except FileNotFoundError:
        state = {}
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("CHAMPION probation state is unreadable") from exc
    current = state.get(activation_id)
    if current is None:
        if paused:
            return {
                "status": "WAITING_FOR_HALT_RESET",
                "buy_blocked": True,
                "activation_id": activation_id,
                "symbol": symbol,
            }
        current = {
            "schema_version": 1,
            "activation_id": activation_id,
            "symbol": symbol,
            "baseline_equity_usdt": format(equity_usdt, "f"),
            "started_at_ms": now_ms,
            "passed_at_ms": None,
            "paused_at_ms": None,
        }
        state[activation_id] = current
        _atomic_json(state_path, state)
    if not isinstance(current, Mapping) or current.get("symbol") != symbol:
        raise RuntimeError("CHAMPION probation state identity differs")
    paused_at = current.get("paused_at_ms")
    if paused:
        if paused_at is None:
            updated = dict(current)
            updated["paused_at_ms"] = now_ms
            state[activation_id] = updated
            _atomic_json(state_path, state)
        return {
            "status": "PAUSED_BY_HALT",
            "buy_blocked": True,
            "activation_id": activation_id,
            "symbol": symbol,
        }
    if paused_at is not None:
        updated = dict(current)
        updated["started_at_ms"] = int(current["started_at_ms"]) + (
            now_ms - int(paused_at)
        )
        updated["paused_at_ms"] = None
        state[activation_id] = updated
        _atomic_json(state_path, state)
        current = updated
    entries, terminals, closed_lifecycles, turnover = _intent_totals(
        journal_path, activation_id=activation_id, symbol=symbol
    )
    maximum_entries = int(probation.get("maximum_entries") or 0)
    minimum_terminals = int(probation.get("minimum_terminal_entries") or 0)
    minimum_closed = int(probation.get("minimum_closed_lifecycles") or 0)
    maximum_turnover = _decimal(
        probation.get("maximum_turnover_usdt"), field="turnover limit"
    )
    maximum_loss = _decimal(
        probation.get("maximum_equity_loss_usdt"), field="loss limit"
    )
    duration_ms = int(probation.get("duration_hours") or 0) * 60 * 60_000
    if (
        maximum_entries <= 0
        or minimum_terminals <= 0
        or minimum_closed <= 0
        or duration_ms <= 0
        or maximum_turnover <= 0
        or maximum_loss <= 0
    ):
        raise RuntimeError("CHAMPION probation limits are invalid")
    baseline = _decimal(current.get("baseline_equity_usdt"), field="baseline")
    loss = max(Decimal("0"), baseline - equity_usdt)
    if loss >= maximum_loss:
        return {
            "status": "FAILED",
            "buy_blocked": True,
            "halt_reason": "CHAMPION probation equity loss limit reached",
            "equity_loss_usdt": format(loss, "f"),
        }
    passed_at = current.get("passed_at_ms")
    expired = now_ms >= int(current["started_at_ms"]) + duration_ms
    if (
        passed_at is None
        and expired
        and terminals >= minimum_terminals
        and closed_lifecycles >= minimum_closed
    ):
        updated = dict(current)
        updated["passed_at_ms"] = now_ms
        state[activation_id] = updated
        _atomic_json(state_path, state)
        passed_at = now_ms
    limit_reached = entries >= maximum_entries or turnover >= maximum_turnover
    status = "PASS" if passed_at is not None else "BLOCKED" if expired else "PROBATION"
    return {
        "status": status,
        "buy_blocked": bool(passed_at is None and (limit_reached or expired)),
        "activation_id": activation_id,
        "symbol": symbol,
        "entries": entries,
        "terminal_entries": terminals,
        "closed_lifecycles": closed_lifecycles,
        "turnover_usdt": format(turnover, "f"),
        "equity_loss_usdt": format(loss, "f"),
        "expires_at_ms": int(current["started_at_ms"]) + duration_ms,
    }


def apply_champion_probation_gate(
    champions: Mapping[str, Mapping[str, object]],
    equity_usdt: Decimal,
    decision: RiskDecision,
    *,
    environ: dict[str, str],
    limits: object,
    create_halt: object,
    now_ms: int,
) -> tuple[dict[str, object], RiskDecision]:
    """Apply probation to one risk decision and publish the worker gate."""
    environ["BOT_CHAMPION_PROBATION_ALLOWED"] = "NO"
    report = evaluate_champion_probation(
        champions,
        journal_path=Path(environ.get("BOT_ORDER_JOURNAL", "")),
        state_path=Path(environ.get(
            "BOT_CHAMPION_PROBATION_STATE",
            "/var/lib/ladder-dragon/control/champion_probation.json",
        )),
        equity_usdt=equity_usdt,
        now_ms=now_ms,
        paused=decision.halted,
    )
    halt_reason = report.get("halt_reason")
    if halt_reason:
        create_halt(
            str(halt_reason),
            limits=limits,
            metadata={"gate": "champion_probation"},
        )
    blocked = bool(report.get("buy_blocked"))
    environ["BOT_CHAMPION_PROBATION_ALLOWED"] = (
        "NO" if blocked or halt_reason else "YES"
    )
    if blocked or halt_reason:
        decision = RiskDecision(
            halted=bool(decision.halted or halt_reason),
            buy_blocked=True,
            reasons=tuple(dict.fromkeys([
                *decision.reasons,
                str(halt_reason or "CHAMPION probation entry limit reached"),
            ])),
        )
    return report, decision


__all__ = ["apply_champion_probation_gate", "evaluate_champion_probation"]
