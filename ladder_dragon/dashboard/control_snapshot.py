# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: derive advisory-control presentation from current canonical readers.
"""Control-state presentation preserves configured-mode and error semantics."""

import json
from typing import Dict
from ladder_dragon.dashboard.control_dependencies import ControlRouteState


def control_snapshot(state: ControlRouteState) -> Dict[str, object]:
    """Handle ai control snapshot."""
    runtime = state._load_ai_runtime_status()
    runtime_ai = runtime.get("ai", {}) if isinstance(runtime.get("ai"), dict) else {}
    configured = bool(runtime_ai.get("enabled"))
    configured_mode = str(runtime_ai.get("configured_mode") or state.AI_MODE).upper()
    control_error = None
    try:
        control = state.read_ai_control(state.AI_CONTROL_FILE)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        control = None
        print(f"[DASHBOARD] AI_CONTROL_READ_FAILED type={type(exc).__name__}", flush=True)
        control_error = "AI_CONTROL_READ_FAILED"
    if control is None:
        enabled = configured and configured_mode != "DISABLED"
        mode = configured_mode if enabled else "DISABLED"
    else:
        enabled = bool(control.get("enabled")) and configured
        mode = configured_mode if enabled else "DISABLED"
    return {
        "configured": configured,
        "enabled": enabled,
        "mode": mode,
        "configured_mode": configured_mode,
        "control_error": control_error,
        "updated_at": control.get("updated_at") if control else None,
    }
