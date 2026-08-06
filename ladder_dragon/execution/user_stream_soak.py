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

from ladder_dragon.execution.user_stream import (
    CURRENT_USER_STREAM_SOAK_EPOCH_ID,
    MAX_USER_STREAM_SOAK_EPOCHS,
    PERSISTED_COUNTERS,
)


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
    maximum_transport_failure_reconnects_per_hour: float = 1.0,
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
    valid_failure_limit = (
        math.isfinite(maximum_transport_failure_reconnects_per_hour)
        and maximum_transport_failure_reconnects_per_hour >= 0
    )
    if not valid_failure_limit:
        reasons.append(
            "maximum transport-failure reconnect rate must be finite and non-negative"
        )
    for path in inputs:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("snapshot is not an object")
            first = float(payload.get("first_observed_at") or 0)
            lifetime_age_hours = (
                max(0.0, current - first) / 3600 if first > 0 else 0.0
            )
            stale_sec = max(0.0, current - path.stat().st_mtime)
            state = str(payload.get("state") or "unknown").lower()
            if payload.get("soak_epoch_error"):
                raise ValueError("producer reported invalid soak epoch evidence")
            raw_epochs = payload.get("soak_epochs")
            if not isinstance(raw_epochs, list):
                raise ValueError("soak epoch history is unavailable")
            if not raw_epochs or len(raw_epochs) > MAX_USER_STREAM_SOAK_EPOCHS:
                raise ValueError("soak epoch history length is invalid")
            seen_epoch_ids: set[str] = set()
            previous_started_at = 0.0
            for raw_epoch in raw_epochs:
                if not isinstance(raw_epoch, Mapping):
                    raise ValueError("soak epoch history contains a non-object")
                if set(raw_epoch) != {"id", "started_at", "baseline"}:
                    raise ValueError("soak epoch history fields are invalid")
                historical_id = str(raw_epoch.get("id") or "")
                historical_start = float(raw_epoch.get("started_at") or 0)
                historical_baseline = raw_epoch.get("baseline")
                if (
                    not historical_id
                    or historical_id in seen_epoch_ids
                    or historical_start <= previous_started_at
                    or not math.isfinite(historical_start)
                    or not isinstance(historical_baseline, Mapping)
                    or set(historical_baseline) != set(PERSISTED_COUNTERS)
                ):
                    raise ValueError("soak epoch history is invalid")
                for name in PERSISTED_COUNTERS:
                    historical_value = int(historical_baseline[name])
                    lifetime_value = int(payload.get(name) or 0)
                    if historical_value < 0 or historical_value > lifetime_value:
                        raise ValueError("soak epoch history counter is invalid")
                seen_epoch_ids.add(historical_id)
                previous_started_at = historical_start
            matching_epochs = [
                row for row in raw_epochs
                if isinstance(row, Mapping)
                and row.get("id") == CURRENT_USER_STREAM_SOAK_EPOCH_ID
            ]
            if len(matching_epochs) != 1:
                raise ValueError("current soak epoch is unavailable or duplicated")
            epoch = matching_epochs[0]
            if raw_epochs[-1] is not epoch:
                raise ValueError("current soak epoch is not latest")
            epoch_started_at = float(epoch.get("started_at") or 0)
            if epoch_started_at <= 0 or not math.isfinite(epoch_started_at):
                raise ValueError("current soak epoch start is invalid")
            if epoch_started_at > current:
                raise ValueError("current soak epoch starts in the future")
            raw_baseline = epoch.get("baseline")
            if not isinstance(raw_baseline, Mapping):
                raise ValueError("current soak epoch baseline is unavailable")
            epoch_counters: dict[str, int] = {}
            lifetime_counters: dict[str, int] = {}
            for name in PERSISTED_COUNTERS:
                lifetime_value = int(payload.get(name) or 0)
                baseline_value = int(raw_baseline.get(name, -1))
                if baseline_value < 0 or lifetime_value < baseline_value:
                    raise ValueError("current soak epoch counter is invalid")
                lifetime_counters[name] = lifetime_value
                epoch_counters[name] = lifetime_value - baseline_value
            age_hours = max(0.0, current - epoch_started_at) / 3600
            reconnects = epoch_counters["reconnects"]
            idle_reconnects = epoch_counters["idle_reconnects"]
            transport_failure_reconnects = epoch_counters[
                "transport_failure_reconnects"
            ]
            controlled_reconnect_drills = epoch_counters[
                "controlled_reconnect_drills"
            ]
            transport_failure_rate = (
                transport_failure_reconnects / age_hours
                if age_hours > 0
                else None
            )
            total_reconnect_rate = (
                reconnects / age_hours
                if age_hours > 0
                else None
            )
            order_events = epoch_counters["order_events"]
            sessions = epoch_counters["sessions"]
            rest_reconciliations = epoch_counters["rest_reconciliations"]
            event_woken_rest = epoch_counters[
                "event_woken_rest_reconciliations"
            ]
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            reasons.append(f"{path}: unreadable snapshot ({type(exc).__name__})")
            continue
        row = {
            "path": str(path),
            "state": state,
            "soak_epoch_id": CURRENT_USER_STREAM_SOAK_EPOCH_ID,
            "soak_epoch_count": len(raw_epochs),
            "age_hours": round(age_hours, 3),
            "lifetime_age_hours": round(lifetime_age_hours, 3),
            "stale_sec": round(stale_sec, 3),
            "sessions": sessions,
            "lifetime_sessions": lifetime_counters["sessions"],
            "reconnects": reconnects,
            "idle_reconnects": idle_reconnects,
            "transport_failure_reconnects": transport_failure_reconnects,
            "controlled_reconnect_drills": controlled_reconnect_drills,
            "lifetime_reconnects": lifetime_counters["reconnects"],
            "reconnects_per_hour": (
                round(total_reconnect_rate, 3)
                if total_reconnect_rate is not None else None
            ),
            "transport_failure_reconnects_per_hour": (
                round(transport_failure_rate, 3)
                if transport_failure_rate is not None else None
            ),
            "order_events": order_events,
            "lifetime_order_events": lifetime_counters["order_events"],
            "rest_reconciliations": rest_reconciliations,
            "lifetime_rest_reconciliations": lifetime_counters[
                "rest_reconciliations"
            ],
            "event_woken_rest_reconciliations": event_woken_rest,
            "lifetime_event_woken_rest_reconciliations": lifetime_counters[
                "event_woken_rest_reconciliations"
            ],
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
        if require_reconnect and controlled_reconnect_drills < 1:
            reasons.append(f"{path}: controlled reconnect has not been observed")
        failure_rate_exceeded = (
            transport_failure_reconnects > 0
            if transport_failure_rate is None
            else transport_failure_rate
            > maximum_transport_failure_reconnects_per_hour
        )
        if valid_failure_limit and failure_rate_exceeded:
            reasons.append(
                f"{path}: transport-failure reconnect rate is too high"
            )
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
