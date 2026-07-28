# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep holdings-sale policy independent from worker orchestration.

"""Holdings policy helpers."""

from typing import Sequence


def effective_remainder_policy(*, requested: bool, live_mode: bool) -> bool:
    """Never allow remainder allocation to bypass per-order CAP in LIVE."""
    return bool(requested and not live_mode)


def protection_state_after_sweep(
    pending_before: Sequence[int],
    remaining: Sequence[int],
    terminal_unfilled: set[int],
) -> str:
    """Summarize protection without calling a zero-fill cancellation pending."""
    if remaining:
        return "pending"
    if pending_before and set(pending_before).issubset(terminal_unfilled):
        return "not_needed"
    return "confirmed" if pending_before else "not_needed"
