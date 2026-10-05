# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind journal telemetry to its own source and observation clock.
"""Read canonical aggregates without granting execution or writing history."""

from datetime import datetime, timezone
from pathlib import Path

from ladder_dragon.execution.order_recovery import read_order_journal_telemetry


def read_journal_status(path: str) -> dict:
    """Timestamp before the read so slow reads cannot refresh stale evidence."""
    if not path:
        return {"available": False, "reason": "order journal path missing"}
    observed_at = datetime.now(timezone.utc).isoformat()
    snapshot = read_order_journal_telemetry(path)
    return {**snapshot, "observed_at": observed_at,
            "source_path": str(Path(path).absolute())}
