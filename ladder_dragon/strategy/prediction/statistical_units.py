# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: derive non-overlapping statistical units from immutable prediction evidence.
"""Select prediction timestamps whose complete outcome intervals cannot overlap."""

from __future__ import annotations

from typing import Iterable, Sequence


def outcome_spacing_ms(horizons_min: Sequence[int]) -> int:
    """Return a start-time gap that prevents inclusive outcome overlap."""
    horizons = tuple(int(value) for value in horizons_min)
    if (
        not horizons
        or any(value <= 0 for value in horizons)
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise ValueError(
            "statistical horizons must be unique increasing positive integers"
        )
    return max(horizons) * 60_000 + 1


def non_overlapping_timestamps(
    timestamps_ms: Iterable[int], *, horizons_min: Sequence[int]
) -> tuple[int, ...]:
    """Select a deterministic prefix-safe set of non-overlapping outcomes."""
    spacing = outcome_spacing_ms(horizons_min)
    selected: list[int] = []
    next_allowed: int | None = None
    for timestamp in sorted({int(value) for value in timestamps_ms}):
        if next_allowed is not None and timestamp < next_allowed:
            continue
        selected.append(timestamp)
        next_allowed = timestamp + spacing
    return tuple(selected)


__all__ = ["non_overlapping_timestamps", "outcome_spacing_ms"]
