#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: send one exact, idempotent Telegram trading digest each morning.
"""Daily Telegram digest built only from the local exact trade ledger."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bin.pnl_24h import _execution, detect_ts_div, iter_trades_until
from ladder_dragon.execution.telegram_alerts import send_message
from ladder_dragon.execution.trade_accounting import UnpricedCommission


ZERO = Decimal("0")
DEFAULT_DB = Path("/home/bot/apps/binance_bot/db/bot_stats.db")
DEFAULT_STATE = Path(
    "/var/lib/ladder-dragon/digests/daily-trading-digest.json"
)
DEFAULT_TIMEZONE = "Asia/Almaty"


@dataclass(frozen=True)
class PeriodSummary:
    """Exact accounting totals for one half-open reporting window."""

    label: str
    start: datetime
    end: datetime
    realized_net_pnl: Decimal
    cash_flow: Decimal
    fees_quote: Decimal
    fills: int
    buys: int
    sells: int


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


def _as_decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not an exact decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _summaries(
    connection: sqlite3.Connection,
    periods: tuple[tuple[str, datetime, datetime], ...],
) -> tuple[PeriodSummary, ...]:
    """Replay exact FIFO lots once and attribute SELL PnL to each period."""
    connection.row_factory = sqlite3.Row
    ts_div = detect_ts_div(connection)
    end_sec = int(max(end for _, _, end in periods).timestamp())
    rows = list(iter_trades_until(connection, end_sec * ts_div - 1, None))
    lots: dict[str, list[list[Decimal]]] = {}
    values = {
        label: {
            "realized": ZERO,
            "cash": ZERO,
            "fees": ZERO,
            "fills": 0,
            "buys": 0,
            "sells": 0,
        }
        for label, _, _ in periods
    }

    for row in rows:
        trade = _execution(row)
        if not trade.symbol.endswith("USDT"):
            raise ValueError(
                f"daily digest cannot combine non-USDT quote asset: {trade.symbol}"
            )
        timestamp = datetime.fromtimestamp(int(row["ts"]) / ts_div, periods[0][1].tzinfo)
        matching = [
            label for label, start, end in periods if start <= timestamp < end
        ]
        fee = trade.valued_commission()
        if matching:
            for label in matching:
                item = values[label]
                item["fills"] += 1
                item["fees"] += fee
                if trade.side == "BUY":
                    item["buys"] += 1
                    item["cash"] -= trade.buy_cost_quote()
                else:
                    item["sells"] += 1
                    item["cash"] += trade.sell_proceeds_quote()

        symbol_lots = lots.setdefault(trade.symbol, [])
        if trade.side == "BUY":
            symbol_lots.append([trade.net_qty, trade.buy_cost_quote()])
            continue

        remaining = trade.net_qty
        proceeds = trade.sell_proceeds_quote()
        matched_cost = ZERO
        matched_qty = ZERO
        while remaining > ZERO and symbol_lots:
            lot_qty, lot_cost = symbol_lots[0]
            take = min(remaining, lot_qty)
            cost_take = lot_cost * take / lot_qty
            matched_cost += cost_take
            matched_qty += take
            remaining -= take
            lot_qty -= take
            lot_cost -= cost_take
            if lot_qty <= ZERO:
                symbol_lots.pop(0)
            else:
                symbol_lots[0] = [lot_qty, lot_cost]
        if remaining > ZERO:
            raise ValueError(
                f"incomplete FIFO history for {trade.symbol}: SELL exceeds known inventory"
            )
        realized = proceeds * matched_qty / trade.net_qty - matched_cost
        for label in matching:
            values[label]["realized"] += realized

    return tuple(
        PeriodSummary(
            label=label,
            start=start,
            end=end,
            realized_net_pnl=_as_decimal(values[label]["realized"], field="realized PnL"),
            cash_flow=_as_decimal(values[label]["cash"], field="cash flow"),
            fees_quote=_as_decimal(values[label]["fees"], field="fees"),
            fills=int(values[label]["fills"]),
            buys=int(values[label]["buys"]),
            sells=int(values[label]["sells"]),
        )
        for label, start, end in periods
    )


def build_digest(db_path: Path, *, now: datetime, timezone_name: str) -> tuple[str, str]:
    """Build an English-only digest and its calendar idempotency key."""
    timezone = _timezone(timezone_name)
    local_now = now.astimezone(timezone)
    periods = _periods(local_now)
    uri = f"file:{db_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=15) as connection:
        summaries = _summaries(connection, periods)

    lines = [
        "🐉 Ladder Dragon — daily trading digest",
        f"Complete data through {periods[0][2].date().isoformat()} 00:00 {timezone_name}",
    ]
    for item in summaries:
        lines.extend(
            (
                "",
                f"{item.label} ({item.start.date()} → {item.end.date()}):",
                f"• Realized FIFO net PnL: {_money(item.realized_net_pnl)}",
                f"• Cash flow: {_money(item.cash_flow)}",
                f"• Fees: {_money(item.fees_quote)}",
                f"• Fills: {item.fills} (BUY {item.buys} / SELL {item.sells})",
            )
        )
    lines.extend(
        (
            "",
            "Cash flow is not profit. Realized PnL is reported only from exact "
            "valued fills and complete FIFO history.",
        )
    )
    return "\n".join(lines), local_now.date().isoformat()


def _last_sent(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("report_date", ""))


def _mark_sent(path: Path, report_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"report_date": report_date}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the daily Telegram trading digest")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("BOT_STATS_DB", DEFAULT_DB)))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"[BLOCKED] exact trade database is unavailable: {args.db}")
        return 2
    try:
        message, report_date = build_digest(
            args.db,
            now=datetime.now(tz=_timezone(args.timezone)),
            timezone_name=args.timezone,
        )
    except (OSError, sqlite3.Error, UnpricedCommission, ValueError) as exc:
        print(f"[BLOCKED] daily trading digest: {type(exc).__name__}: {exc}")
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
    _mark_sent(args.state, report_date)
    print(f"[OK] daily trading digest sent for {report_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
