# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve AI-status presentation through explicit component ownership.

from datetime import datetime


def runtime_context(deps, runtime):
    runtime_ai = runtime.get("ai", {}) if isinstance(runtime.get("ai"), dict) else {}
    runtime_budgets = (
        runtime_ai.get("budgets", {})
        if isinstance(runtime_ai.get("budgets"), dict) else {}
    )
    runtime_age_sec = None
    try:
        runtime_age_sec = max(
            0,
            int(deps.time.time() - datetime.fromisoformat(runtime["updated_at"]).timestamp()),
        )
    except (KeyError, TypeError, ValueError):
        pass
    runtime_stale = bool(
        runtime and (runtime_age_sec is None or runtime_age_sec > 90)
    )
    effective_mode = str(runtime_ai.get("mode") or deps.AI_MODE).upper()
    return runtime_ai, runtime_budgets, runtime_age_sec, runtime_stale, effective_mode
