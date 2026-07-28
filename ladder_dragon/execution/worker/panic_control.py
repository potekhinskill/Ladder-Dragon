# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: classify panic BUY blocks and recovery restarts without side effects.

"""Pure PANIC state decisions."""

from typing import Sequence


def panic_buy_block_reason(
    existing_reason: str | None,
    *,
    live_mode: bool,
    raw_signal: bool,
    debounced_active: bool,
    skip_while_panic: bool,
) -> str | None:
    """Keep the debounce window from becoming a LIVE exposure window."""
    if existing_reason is not None:
        return existing_reason
    if live_mode and raw_signal:
        return "panic-raw-signal"
    if debounced_active and (live_mode or skip_while_panic):
        return "panic"
    return None


def panic_recovery_restart_required(
    *,
    live_mode: bool,
    was_active: bool,
    is_active: bool,
    tracked_buy_order_ids: Sequence[int],
) -> bool:
    """Request a fresh gated worker after a confirmed LIVE panic recovery."""
    return bool(
        live_mode
        and was_active
        and not is_active
        and not tracked_buy_order_ids
    )
