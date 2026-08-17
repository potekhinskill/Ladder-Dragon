# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep independent strategy-control approvals outside the supervisor monolith.
"""Resolve evidence and operator approval for separate strategy controls."""

from __future__ import annotations

import os
import sqlite3
from typing import Callable, Mapping, MutableMapping

from ladder_dragon.strategy.prediction.control_evidence import CONTROL_KINDS
from ladder_dragon.strategy.prediction.control_approval import (
    control_specific_gate,
)
from ladder_dragon.strategy.prediction.statistical_evidence import (
    resolved_independent_evidence,
)


CONTROL_APPROVAL_VARIABLES = {
    "expectancy": "BOT_EXPECTANCY_APPROVED",
    "inventory": "BOT_INVENTORY_SKEW_APPROVED",
    "maker": "BOT_MAKER_POLICY_APPROVED",
    "regime": "BOT_REGIME_GATE_APPROVED",
}


def control_gate(
    symbol: str,
    control: str,
    *,
    store: object | None,
    cache: MutableMapping[str, tuple[float, dict[str, object]]],
    now_monotonic: float,
    applicable: bool | None = None,
) -> dict[str, object]:
    """Return current evidence for one execution-changing control."""
    normalized = str(control).strip().lower()
    if normalized not in CONTROL_KINDS:
        raise ValueError("unknown strategy control")
    cache_key = f"{symbol.upper()}:{normalized}:{applicable}"
    cached = cache.get(cache_key)
    if cached is not None and now_monotonic - cached[0] < 60:
        return cached[1]
    if store is None:
        result = _blocked("prediction journal is unavailable")
    else:
        try:
            if hasattr(store, "_connect"):
                evidence = resolved_independent_evidence(
                    store,
                    symbol,
                    kind=CONTROL_KINDS[normalized],
                    required_horizons_min=(1, 5, 15),
                )
                samples = evidence.samples
            else:
                # Small injected test adapters do not expose SQLite internals.
                evidence = None
                samples = store.resolved_samples(
                    symbol, kind=CONTROL_KINDS[normalized]
                )
            result = control_specific_gate(
                normalized, samples, applicable=applicable
            )
            if evidence is not None:
                result["statistical_reader"] = {
                    "scanned_snapshots": evidence.scanned_snapshots,
                    "excluded_overlapping_snapshots": (
                        evidence.excluded_overlapping_snapshots
                    ),
                    "stopped_at_pending_snapshot": (
                        evidence.stopped_at_pending_snapshot
                    ),
                    "bounded_memory": True,
                }
        except (OSError, sqlite3.Error, TypeError, ValueError):
            result = _blocked("strategy gate evidence is unreadable")
    cache[cache_key] = (now_monotonic, result)
    return result


def control_apply_allowed(
    symbol: str,
    control: str,
    *,
    gate_loader: Callable[[str, str], dict[str, object]],
    environ: Mapping[str, str] = os.environ,
) -> tuple[bool, dict[str, object]]:
    """Require the control's own approval and statistical evidence."""
    normalized = str(control).strip().lower()
    try:
        approval_name = CONTROL_APPROVAL_VARIABLES[normalized]
    except KeyError as exc:
        raise ValueError("unknown strategy control") from exc
    gate = gate_loader(symbol, normalized)
    approved = environ.get(approval_name, "").strip().upper() == "YES"
    return approved and bool(gate.get("approved")), gate


def evaluate_control_requests(
    symbol: str,
    modes: Mapping[str, str],
    *,
    apply_allowed: Callable[
        [str, str], tuple[bool, dict[str, object]]
    ],
) -> dict[str, object]:
    """Evaluate each requested control against only its own gate."""
    permissions: dict[str, bool] = {}
    gates: dict[str, dict[str, object]] = {}
    # Resolve every control independently for telemetry. Only controls that
    # request APPLY participate in the combined execution decision.
    for control in modes:
        permissions[control], gates[control] = apply_allowed(symbol, control)
    requested = [control for control, mode in modes.items() if mode == "APPLY"]
    return {
        "permissions": permissions,
        "gates": gates,
        "requested": requested,
        "approved": bool(requested) and all(
            permissions[control] for control in requested
        ),
        "blocked": any(not permissions[control] for control in requested),
    }


def statistical_challenger_mode(value: str) -> str:
    """Reject an APPLY mode that has no execution consumer."""
    normalized = str(value).strip().upper()
    if normalized not in {"OFF", "SHADOW"}:
        raise ValueError(
            "BOT_STATISTICAL_REGIME_MODE supports only OFF or SHADOW"
        )
    return normalized


def _blocked(reason: str) -> dict[str, object]:
    return {"approved": False, "mode": "SHADOW", "reasons": [reason]}


__all__ = [
    "CONTROL_APPROVAL_VARIABLES",
    "control_apply_allowed",
    "control_gate",
    "evaluate_control_requests",
    "statistical_challenger_mode",
]
