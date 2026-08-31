# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define one depth-update volatility population for replay and runtime.
"""Shared exact volatility measurement for public depth updates."""

from __future__ import annotations

from decimal import Decimal


VOLATILITY_EVENT_POPULATION = "SEQUENCE_VERIFIED_DEPTH_UPDATE_TOP_MID_V1"
VOLATILITY_MEASUREMENT_WINDOW_MS = 55 * 60_000
VOLATILITY_METRIC = "DEPTH_UPDATE_TOP_MID_MOVE_P95_BPS_OVER_55_MINUTES_V2"


def observe_depth_mid(
    *, event_type: str, bid: Decimal, ask: Decimal,
    previous_mid: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Return the next depth-update mid and its absolute move in basis points."""
    if event_type != "depthUpdate":
        return previous_mid, None
    if bid <= 0 or ask <= bid:
        raise ValueError("volatility depth book is invalid")
    mid = (bid + ask) / Decimal("2")
    move = (
        None if previous_mid is None
        else abs(mid / previous_mid - Decimal("1")) * Decimal("10000")
    )
    return mid, move


__all__ = [
    "VOLATILITY_EVENT_POPULATION",
    "VOLATILITY_MEASUREMENT_WINDOW_MS",
    "VOLATILITY_METRIC",
    "observe_depth_mid",
]
