# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: audit sanitized User Data Stream soak evidence.
"""Read-only readiness audit for notification-only User Data Stream state."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Iterable, Mapping


@dataclass(frozen=True)
class UserStreamSoakAudit:
    ready: bool
    reasons: tuple[str, ...]
    streams: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "reasons": list(self.reasons),
            "streams": list(self.streams),
            "rest_remains_authoritative": True,
        }


def audit_user_stream_soak(
    paths: Iterable[Path],
    *,
    minimum_hours: float = 24.0,
    maximum_stale_sec: float = 180.0,
    maximum_reconnects_per_hour: float = 1.0,
    require_reconnect: bool = False,
    require_order_event: bool = False,
    require_event_woken_rest: bool = False,
    now: float | None = None,
) -> UserStreamSoakAudit:
    """Validate sanitized soak duration without treating WS as authoritative."""
    current = time.time() if now is None else now
    reasons: list[str] = []
    streams: list[dict[str, object]] = []
    inputs = tuple(paths)
    if not inputs:
        reasons.append("no User Data Stream snapshots were supplied")
    valid_reconnect_limit = (
        math.isfinite(maximum_reconnects_per_hour)
        and maximum_reconnects_per_hour >= 0
    )
    if not valid_reconnect_limit:
        reasons.append("maximum reconnect rate must be finite and non-negative")
    for path in inputs:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("snapshot is not an object")
            first = float(payload.get("first_observed_at") or 0)
            age_hours = max(0.0, current - first) / 3600 if first > 0 else 0.0
            stale_sec = max(0.0, current - path.stat().st_mtime)
            state = str(payload.get("state") or "unknown").lower()
            reconnects = int(payload.get("reconnects") or 0)
            if reconnects < 0:
                raise ValueError("reconnect counter is negative")
            reconnect_rate = (
                reconnects / age_hours
                if age_hours > 0
                else None
            )
            order_events = int(payload.get("order_events") or 0)
            sessions = int(payload.get("sessions") or 0)
            rest_reconciliations = int(payload.get("rest_reconciliations") or 0)
            event_woken_rest = int(
                payload.get("event_woken_rest_reconciliations") or 0
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            reasons.append(f"{path}: unreadable snapshot ({type(exc).__name__})")
            continue
        row = {
            "path": str(path),
            "state": state,
            "age_hours": round(age_hours, 3),
            "stale_sec": round(stale_sec, 3),
            "sessions": sessions,
            "reconnects": reconnects,
            "reconnects_per_hour": (
                round(reconnect_rate, 3) if reconnect_rate is not None else None
            ),
            "order_events": order_events,
            "rest_reconciliations": rest_reconciliations,
            "event_woken_rest_reconciliations": event_woken_rest,
        }
        streams.append(row)
        if state != "connected":
            reasons.append(f"{path}: stream is not connected")
        if age_hours < minimum_hours:
            reasons.append(f"{path}: soak duration is below {minimum_hours:g} hours")
        if stale_sec > maximum_stale_sec:
            reasons.append(f"{path}: snapshot is stale")
        if sessions < 1:
            reasons.append(f"{path}: no authenticated session is recorded")
        if require_reconnect and reconnects < 1:
            reasons.append(f"{path}: reconnect has not been observed")
        reconnect_rate_exceeded = (
            reconnects > 0
            if reconnect_rate is None
            else reconnect_rate > maximum_reconnects_per_hour
        )
        if valid_reconnect_limit and reconnect_rate_exceeded:
            reasons.append(f"{path}: reconnect rate is too high for a stable soak")
        if require_order_event and order_events < 1:
            reasons.append(f"{path}: no order event has been observed")
        if require_event_woken_rest and event_woken_rest < 1:
            reasons.append(
                f"{path}: no event-triggered REST reconciliation was observed"
            )
    return UserStreamSoakAudit(
        ready=not reasons,
        reasons=tuple(reasons),
        streams=tuple(streams),
    )
