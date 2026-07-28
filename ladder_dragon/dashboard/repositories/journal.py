# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose sanitized order-journal telemetry to the dashboard.

"""Read-only order-journal repository."""

from pathlib import Path
from typing import Any

from ladder_dragon.execution.order_recovery import read_order_journal_telemetry


def journal_telemetry(path: str | Path) -> dict[str, Any]:
    """Read sanitized telemetry using the journal's authoritative reader."""
    return read_order_journal_telemetry(path)
