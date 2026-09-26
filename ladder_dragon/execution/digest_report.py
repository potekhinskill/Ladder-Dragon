# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own one daily digest boundary without changing accounting behavior.
"""Daily digest report ownership."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ladder_dragon.execution.digest_totals import ZERO
from ladder_dragon.execution.digest_fifo import _summaries


def _money(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "+" if rounded > ZERO else ""
    return f"{sign}{rounded} USDT"


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown reporting timezone: {name}") from exc


def _periods(now: datetime) -> tuple[tuple[str, datetime, datetime], ...]:
    """Return complete local periods ending at today's midnight."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        ("Yesterday", today - timedelta(days=1), today),
        ("Last 7 complete days", today - timedelta(days=7), today),
        ("Last 30 complete days", today - timedelta(days=30), today),
    )


def build_digest(db_path: Path, *, now: datetime, timezone_name: str) -> tuple[str, str]:
    """Build an English-only digest and its calendar idempotency key."""
    timezone = _timezone(timezone_name)
    local_now = now.astimezone(timezone)
    periods = _periods(local_now)
    uri = f"file:{db_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=15) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        summaries, exclusions = _summaries(connection, periods)

    lines = [
        "🐉 Ladder Dragon — daily trading digest",
        f"Ledger periods through {periods[0][2].date().isoformat()} 00:00 {timezone_name}",
        "Closed-cycle net PnL: UNAVAILABLE (this ledger does not prove entry-to-exit ownership).",
    ]
    if any(item.legacy_source for item in summaries):
        lines.append(
            "WARNING: LEGACY FIFO estimates use records whose original precision is not verified."
        )
    for item in summaries:
        # Keep uncertainty beside the amount, including positive legacy results.
        pnl_label = (
            "FIFO net PnL estimate (UNVERIFIED LEGACY)"
            if item.legacy_source else "Realized FIFO net PnL"
        )
        lines.extend(
            (
                "",
                f"{item.label} ({item.start.date()} → {item.end.date()}):",
                f"• {pnl_label}: {_money(item.realized_net_pnl)}",
                f"  FIFO cost of sold inventory: {_money(item.fifo_cost)}",
                f"  Cost from purchases before this period: {_money(item.prior_period_cost)}",
                "• Source quality: " + (
                    "no eligible fills" if not item.fills else
                    "LEGACY included; original precision is not verified"
                    if item.legacy_source else
                    "valued ledger records; exchange history not independently verified"
                ),
                f"• Cash flow: {_money(item.cash_flow)}",
                # Fees are stored as a positive expense but displayed as their
                # negative contribution to account cash and net performance.
                f"• Fees: {_money(-item.fees_quote)}",
                f"• Fills: {item.fills} (BUY {item.buys} / SELL {item.sells})",
            )
        )
    lines.extend(
        (
            "",
            "FIFO uses the oldest recorded purchases, including purchases before the report period.",
            "FIFO PnL is not the result of this period's trading cycles or the change in portfolio value.",
            "Cash flow is not profit. Fees are already included; do not subtract them again.",
            "Figures cover included symbols only. Ledger coverage does not prove complete exchange history.",
        )
    )
    if exclusions:
        lines.extend(("", "Excluded symbols:"))
        lines.extend(f"• {item}" for item in exclusions)
    return "\n".join(lines), local_now.date().isoformat()
