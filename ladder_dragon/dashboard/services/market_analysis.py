# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose bounded SHADOW scenario status to the dashboard.
"""Read the multi-symbol scenario status without opening execution state."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time


MAX_STATUS_BYTES = 512 * 1024
DEFAULT_STATUS = Path("/var/lib/ladder-dragon/market-analysis/status.json")


def market_analysis_snapshot(path: Path | None = None) -> dict[str, object]:
    """Return one bounded status document or a safe unavailable payload."""
    source = path or Path(os.getenv(
        "BOT_MARKET_ANALYSIS_STATUS_FILE", str(DEFAULT_STATUS)
    ))
    try:
        if source.stat().st_size > MAX_STATUS_BYTES:
            raise ValueError("status is oversized")
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("status must be an object")
        generated = datetime.fromisoformat(str(payload["generated_at"]))
        if generated.tzinfo is None:
            raise ValueError("status time must include timezone")
        age_sec = max(0, int(time.time() - generated.timestamp()))
        return {
            "ok": True,
            "stale": age_sec > 7_200,
            "age_sec": age_sec,
            **payload,
            "mode": "SHADOW",
            "apply_allowed": False,
            "can_change_orders": False,
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {
            "ok": False,
            "status": "UNAVAILABLE",
            "mode": "SHADOW",
            "apply_allowed": False,
            "can_change_orders": False,
            "results": [],
            "failures": [],
        }
