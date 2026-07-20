# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: audit sanitized User Data Stream soak evidence.
"""Read-only readiness audit for notification-only User Data Stream state."""

from __future__ import annotations

from dataclasses import dataclass
import json
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
    require_reconnect: bool = False,
    require_order_event: bool = False,
    now: float | None = None,
) -> UserStreamSoakAudit:
    """Validate sanitized soak duration without treating WS as authoritative."""
    current = time.time() if now is None else now
    reasons: list[str] = []
    streams: list[dict[str, object]] = []
    inputs = tuple(paths)
    if not inputs:
        reasons.append("no User Data Stream snapshots were supplied")
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
            order_events = int(payload.get("order_events") or 0)
            sessions = int(payload.get("sessions") or 0)
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
            "order_events": order_events,
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
        if require_order_event and order_events < 1:
            reasons.append(f"{path}: no order event has been observed")
    return UserStreamSoakAudit(
        ready=not reasons,
        reasons=tuple(reasons),
        streams=tuple(streams),
    )
