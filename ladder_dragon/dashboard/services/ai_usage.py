# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve dashboard AI reporting with explicit service ownership.

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict


def usage_today(deps, path: Path, *, now: datetime | None = None) -> Dict:
    # Limits and DEGRADED state must match AI policy and reset on UTC boundaries.
    # APP_TZ is used only for local-time presentation.
    now = now or datetime.now(tz=timezone.utc)
    now = now.astimezone(timezone.utc)
    today = now.date()
    cache_key = f"usage:{path}:{today.isoformat()}"
    cached = deps._ai_cache_get(cache_key)
    if cached is not None:
        return cached
    requests_count = tokens = errors = recent_errors = 0
    cost = Decimal("0")
    last_error_at = None
    if not path.exists():
        return deps._ai_cache_put(cache_key, {
            "requests": 0,
            "tokens": 0,
            "cost_usd": "0",
            "errors": 0,
            "recent_errors": 0,
            "last_error_at": None,
            "error_window_sec": deps.AI_ERROR_DEGRADED_WINDOW_SEC,
        })
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
            stamp = datetime.fromisoformat(str(event["timestamp"])).astimezone(timezone.utc)
            if stamp.date() != today:
                continue
            requests_count += 1
            tokens += int(event.get("total_tokens") or 0)
            cost += Decimal(str(event.get("estimated_cost_usd") or "0"))
            if event.get("outcome") == "error":
                errors += 1
                last_error_at = max(last_error_at or stamp, stamp).isoformat()
                age = (now - stamp).total_seconds()
                if 0 <= age <= deps.AI_ERROR_DEGRADED_WINDOW_SEC:
                    recent_errors += 1
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return deps._ai_cache_put(cache_key, {
        "requests": requests_count,
        "tokens": tokens,
        "cost_usd": str(cost),
        "errors": errors,
        "recent_errors": recent_errors,
        "last_error_at": last_error_at,
        "error_window_sec": deps.AI_ERROR_DEGRADED_WINDOW_SEC,
    })
