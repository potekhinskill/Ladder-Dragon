# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the venue config component of the execution layer.
"""Venue-specific local state paths.

Testnet must never share risk state, statistics, or order intents with Mainnet.
"""

from __future__ import annotations

import os
from pathlib import Path


def _path(value: str) -> Path:
    """Return one normalized path for isolation comparisons."""
    return Path(value).expanduser().resolve(strict=False)


def apply_testnet_paths() -> None:
    """Select complete Testnet state and reject Mainnet path reuse."""
    project_dir = Path(
        os.getenv("PROJECT_DIR", "").strip()
        or Path(__file__).resolve().parents[2]
    )
    default_db_dir = project_dir / "db"
    stats_db = os.getenv("BOT_TESTNET_STATS_DB", "").strip() or str(
        default_db_dir / "testnet_bot_stats.db"
    )
    journal = os.getenv("BOT_TESTNET_ORDER_JOURNAL", "").strip() or str(
        default_db_dir / "testnet_order_intents.sqlite3"
    )
    run_dir_raw = os.getenv("BOT_TESTNET_RUN_DIR", "").strip() or "/run/mybot/testnet"

    main_stats = (
        os.getenv("BOT_MAINNET_STATS_DB", "").strip()
        or os.getenv("BOT_STATS_DB", "").strip()
        or str(default_db_dir / "bot_stats.db")
    )
    main_journal = (
        os.getenv("BOT_MAINNET_ORDER_JOURNAL", "").strip()
        or os.getenv("BOT_ORDER_JOURNAL", "").strip()
        or str(default_db_dir / "order_intents.sqlite3")
    )
    main_run_dir = (
        os.getenv("BOT_MAINNET_RUN_DIR", "").strip()
        or os.getenv("BOT_RUN_DIR", "").strip()
        or "/run/mybot"
    )

    targets = {
        "statistics database": _path(stats_db),
        "order journal": _path(journal),
        "runtime directory": _path(run_dir_raw),
    }
    mainnet = {
        "statistics database": _path(main_stats),
        "order journal": _path(main_journal),
        "runtime directory": _path(main_run_dir),
    }
    reused = [name for name, target in targets.items() if target == mainnet[name]]
    if reused:
        raise RuntimeError(
            "Testnet path isolation failed for " + ", ".join(reused)
        )
    if targets["statistics database"] == targets["order journal"]:
        raise RuntimeError("Testnet statistics and order journal paths must differ")

    # Apply the complete set only after every isolation check passes.
    run_dir = Path(run_dir_raw)
    os.environ.update(
        {
            "BOT_STATS_DB": stats_db,
            "BOT_ORDER_JOURNAL": journal,
            "BOT_RUN_DIR": str(run_dir),
            "CB_HALT_FILE": str(run_dir / "circuit_halt.json"),
            "CB_STATE_FILE": str(run_dir / "risk_state.json"),
            "CB_ALERTS_FILE": str(run_dir / "risk_alerts.ndjson"),
        }
    )
