# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own one daily digest boundary without changing accounting behavior.
"""Daily digest command ownership."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sqlite3

from ladder_dragon.execution.digest_report import _timezone, build_digest
from ladder_dragon.execution.digest_state import _last_sent, _last_alert, _mark_state
from ladder_dragon.execution.telegram_alerts import send_message
from ladder_dragon.execution.trade_accounting import UnpricedCommission

DEFAULT_DB = Path("/home/bot/apps/binance_bot/db/bot_stats.db")
DEFAULT_STATE = Path("/var/lib/ladder-dragon/digests/daily-trading-digest.json")
DEFAULT_TIMEZONE = "Asia/Almaty"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the daily Telegram trading digest")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("BOT_STATS_DB", DEFAULT_DB)))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    timezone = _timezone(args.timezone)
    report_date = datetime.now(tz=timezone).date().isoformat()
    try:
        if not args.db.is_file():
            raise FileNotFoundError("exact trade database is unavailable")
        message, report_date = build_digest(
            args.db,
            now=datetime.now(tz=timezone),
            timezone_name=args.timezone,
        )
    except (OSError, sqlite3.Error, UnpricedCommission, ValueError) as exc:
        print(f"[BLOCKED] daily trading digest: {type(exc).__name__}: {exc}")
        if not args.dry_run and _last_alert(args.state) != report_date:
            warning = (
                "🐉 Ladder Dragon — daily trading digest BLOCKED\n"
                f"Report date: {report_date}\n"
                f"Reason: {type(exc).__name__}\n"
                "No financial figures were sent."
            )
            if send_message(warning):
                _mark_state(
                    args.state,
                    blocked_alert_date=report_date,
                )
        return 2
    if args.dry_run:
        print(message)
        return 0
    if _last_sent(args.state) == report_date:
        print(f"[OK] daily trading digest already sent for {report_date}")
        return 0
    if not send_message(message):
        print("[FAILED] Telegram delivery was not confirmed")
        return 1
    _mark_state(args.state, report_date=report_date)
    print(f"[OK] daily trading digest sent for {report_date}")
    return 0
