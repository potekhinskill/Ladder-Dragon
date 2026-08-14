# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: derive sanitized User Stream epoch metrics for the dashboard.
"""Read display-only metrics from one immutable User Stream soak epoch."""

from __future__ import annotations

import math
from typing import Mapping


_EPOCH_COUNTER_FIELDS = (
    "sessions",
    "order_events",
    "idle_reconnects",
    "controlled_reconnect_drills",
    "transport_failure_reconnects",
    "connection_attempts",
    "disconnects",
)


def empty_soak_epoch_metrics() -> dict[str, object]:
    return {
        "soak_epoch_id": None,
        "soak_epoch_hours": 0.0,
        "soak_epoch_reconnects": 0,
        "soak_epoch_order_events": 0,
        "soak_epoch_sessions": 0,
        "soak_epoch_planned_reconnects": 0,
        "soak_epoch_failure_reconnects": 0,
        "soak_epoch_connection_attempts": 0,
        "soak_epoch_disconnects": 0,
    }


def current_soak_epoch_metrics(
    payload: Mapping[str, object],
    *,
    now: float,
) -> dict[str, object]:
    """Return safe display metrics without making a readiness decision."""
    result = empty_soak_epoch_metrics()
    epoch_id = str(payload.get("current_soak_epoch_id") or "")
    raw_epochs = payload.get("soak_epochs")
    if not epoch_id or not isinstance(raw_epochs, list):
        return result
    matching = [
        row for row in raw_epochs
        if isinstance(row, Mapping) and row.get("id") == epoch_id
    ]
    if len(matching) != 1:
        return result
    epoch = matching[0]
    try:
        started_at = float(epoch.get("started_at") or 0)
        baseline = epoch.get("baseline")
        if (
            started_at <= 0
            or not math.isfinite(started_at)
            or not isinstance(baseline, Mapping)
        ):
            return result
        counters = {
            name: max(
                0,
                int(payload.get(name) or 0)
                - int(baseline.get(name) or 0),
            )
            for name in ("reconnects", *_EPOCH_COUNTER_FIELDS)
        }
    except (TypeError, ValueError, OverflowError):
        return result
    return {
        "soak_epoch_id": epoch_id,
        "soak_epoch_hours": round(max(0.0, now - started_at) / 3600, 2),
        "soak_epoch_reconnects": counters["reconnects"],
        "soak_epoch_order_events": counters["order_events"],
        "soak_epoch_sessions": counters["sessions"],
        "soak_epoch_planned_reconnects": (
            counters["idle_reconnects"]
            + counters["controlled_reconnect_drills"]
        ),
        "soak_epoch_failure_reconnects": counters[
            "transport_failure_reconnects"
        ],
        "soak_epoch_connection_attempts": counters["connection_attempts"],
        "soak_epoch_disconnects": counters["disconnects"],
    }
