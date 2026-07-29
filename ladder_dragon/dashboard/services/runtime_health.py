# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: classify sanitized dashboard runtime health without exposing raw evidence.

"""Small policies for presenting the bot's fail-closed runtime state."""

from typing import Mapping


def runtime_degraded_reason(
    runtime: Mapping[str, object],
    *,
    follow_bot_paths: bool,
    stale: bool,
) -> str | None:
    """Return one bounded diagnostic code for a non-running bot runtime."""
    if stale:
        return "runtime:stale"
    if not runtime:
        return "runtime:unavailable" if follow_bot_paths else None
    state = str(runtime.get("state") or "").strip().lower()
    return None if state == "running" else f"runtime:{state or 'unknown'}"
