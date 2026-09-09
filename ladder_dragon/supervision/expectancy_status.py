# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: serialize expectancy diagnostics without changing strategy controls.
"""Status construction has no execution authority or mutable runtime access."""


def build_expectancy_status(*, mode, required_edge, commission_error, maker_mode,
                            configuration_passes, minimum_profit, take_profit):
    """Preserve diagnostic values and exact decimal text from the current cycle."""
    return {
        "mode": mode,
        "required_edge_pct": str(required_edge) if required_edge is not None else None,
        "commission_error": commission_error,
        "maker_policy_mode": maker_mode,
        "configuration_passes": configuration_passes,
        "configuration_warning": (
            "required_edge_unavailable" if required_edge is None else
            "configured_returns_below_required_edge" if not configuration_passes else None
        ),
        "configuration_blocks_buys": mode == "APPLY" and not configuration_passes,
        "configured_minimum_net_pct": str(minimum_profit),
        "configured_take_profit_pct": str(take_profit),
    }
