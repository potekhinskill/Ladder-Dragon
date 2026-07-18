# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Venue-specific local state paths.

Testnet must never share risk state, statistics, or order intents with Mainnet.
"""

from __future__ import annotations

import os
from pathlib import Path


def apply_testnet_paths() -> None:
    """Select explicitly configured Testnet state without changing Mainnet defaults."""
    stats_db = os.getenv("BOT_TESTNET_STATS_DB", "").strip()
    journal = os.getenv("BOT_TESTNET_ORDER_JOURNAL", "").strip()
    run_dir_raw = os.getenv("BOT_TESTNET_RUN_DIR", "").strip()

    if stats_db:
        os.environ["BOT_STATS_DB"] = stats_db
    if journal:
        os.environ["BOT_ORDER_JOURNAL"] = journal
    if run_dir_raw:
        run_dir = Path(run_dir_raw)
        os.environ["BOT_RUN_DIR"] = str(run_dir)
        os.environ["CB_HALT_FILE"] = str(run_dir / "circuit_halt.json")
        os.environ["CB_STATE_FILE"] = str(run_dir / "risk_state.json")
        os.environ["CB_ALERTS_FILE"] = str(run_dir / "risk_alerts.ndjson")
