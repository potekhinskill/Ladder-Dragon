# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: normalize host telemetry values without shell access.

"""Host telemetry value helpers."""


def bounded_percent(value: object) -> float:
    """Clamp presentation telemetry into the conventional percent range."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, max(0.0, parsed))
