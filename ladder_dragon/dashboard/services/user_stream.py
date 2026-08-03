# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: derive sanitized User Stream epoch metrics for the dashboard.
"""Read display-only metrics from one immutable User Stream soak epoch."""

from __future__ import annotations

import math
from typing import Mapping


def current_soak_epoch_metrics(
    payload: Mapping[str, object],
    *,
    now: float,
) -> dict[str, object]:
    """Return safe display metrics without making a readiness decision."""
    result: dict[str, object] = {
        "soak_epoch_id": None,
        "soak_epoch_hours": 0.0,
        "soak_epoch_reconnects": 0,
        "soak_epoch_order_events": 0,
    }
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
        reconnects = max(
            0,
            int(payload.get("reconnects") or 0)
            - int(baseline.get("reconnects") or 0),
        )
        order_events = max(
            0,
            int(payload.get("order_events") or 0)
            - int(baseline.get("order_events") or 0),
        )
    except (TypeError, ValueError, OverflowError):
        return result
    return {
        "soak_epoch_id": epoch_id,
        "soak_epoch_hours": round(max(0.0, now - started_at) / 3600, 2),
        "soak_epoch_reconnects": reconnects,
        "soak_epoch_order_events": order_events,
    }
