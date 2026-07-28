# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce per-symbol supervisor limits independently of orchestration.

"""Pure per-symbol policy helpers."""

from decimal import Decimal


def cap_scaling_inactive_reason(
    cap: Decimal,
    *,
    inventory_mode: str,
    regime_mode: str,
) -> str | None:
    """Explain why enabled inventory/regime CAP controls cannot scale."""
    enabled = [
        name
        for name, mode in (
            ("inventory", inventory_mode),
            ("regime", regime_mode),
        )
        if str(mode).upper() != "OFF"
    ]
    if cap > 0 or not enabled:
        return None
    return (
        "BOT_CAP_PER_ORDER is not positive; inactive_controls="
        + ",".join(enabled)
    )


def limit_target_buys(desired: int, operator_limit: int) -> int:
    """Keep adaptive buy-count changes inside the operator's hard ceiling."""
    ceiling = max(1, int(operator_limit))
    return min(max(1, int(desired)), ceiling)
