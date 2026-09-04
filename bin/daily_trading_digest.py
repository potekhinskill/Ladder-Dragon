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
    fifo_cost: Decimal
    prior_period_cost: Decimal
    legacy_source: bool


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
) -> tuple[tuple[PeriodSummary, ...], tuple[str, ...]]:
    """Replay symbols independently and exclude incomplete FIFO histories."""
    connection.row_factory = sqlite3.Row
    ts_div = detect_ts_div(connection)
    end_sec = int(max(end for _, _, end in periods).timestamp())
    rows = list(iter_trades_until(connection, end_sec * ts_div - 1, None))
    lots: dict[str, list[list]] = {}
    values = {
        label: {}
        for label, _, _ in periods
    }
    excluded: dict[str, str] = {}

    for row in rows:
        symbol = str(row["symbol"] or "").strip().upper()
        if not symbol or symbol in excluded:
            continue
        try:
            trade = _execution(row)
            fee = trade.valued_commission()
        except (ArithmeticError, TypeError, ValueError, UnpricedCommission):
            excluded[symbol] = "unpriced or invalid exact trade data"
            continue
        if not trade.symbol.endswith("USDT"):
            excluded[symbol] = "non-USDT quote asset"
            continue
        timestamp = datetime.fromtimestamp(int(row["ts"]) / ts_div, periods[0][1].tzinfo)
        matching = [
            label for label, start, end in periods if start <= timestamp < end
        ]
        if matching:
            for label in matching:
                item = values[label].setdefault(
                    symbol,
                    {
                        "realized": ZERO,
                        "cash": ZERO,
                        "fees": ZERO,
                        "fills": 0,
                        "buys": 0,
                        "sells": 0,
                        "fifo_cost": ZERO,
                        "prior_cost": ZERO,
                        "legacy": False,
                    },
                )
                item["fills"] += 1
                item["fees"] += fee
                item["legacy"] |= trade.commission_value_status == "legacy"
                if trade.side == "BUY":
                    item["buys"] += 1
                    item["cash"] -= trade.buy_cost_quote()
                else:
                    item["sells"] += 1
                    item["cash"] += trade.sell_proceeds_quote()

        symbol_lots = lots.setdefault(trade.symbol, [])
        if trade.side == "BUY":
            symbol_lots.append([
                trade.net_qty, trade.buy_cost_quote(), timestamp,
                trade.commission_value_status == "legacy",
            ])
            continue

        remaining = trade.net_qty
        proceeds = trade.sell_proceeds_quote()
        matched_cost = ZERO
        matched_qty = ZERO
        while remaining > ZERO and symbol_lots:
            lot_qty, lot_cost, acquired_at, legacy = symbol_lots[0]
            take = min(remaining, lot_qty)
            cost_take = lot_cost * take / lot_qty
            matched_cost += cost_take
            for label, start, end in periods:
                if label in matching:
                    item = values[label][symbol]
                    item["fifo_cost"] += cost_take
                    if acquired_at < start:
                        item["prior_cost"] += cost_take
                    item["legacy"] |= legacy
            matched_qty += take
            remaining -= take
            lot_qty -= take
            lot_cost -= cost_take
            if lot_qty <= ZERO:
                symbol_lots.pop(0)
            else:
                symbol_lots[0] = [lot_qty, lot_cost, acquired_at, legacy]
        if remaining > ZERO:
            excluded[symbol] = "incomplete FIFO history"
            continue
        realized = proceeds * matched_qty / trade.net_qty - matched_cost
        for label in matching:
            values[label][symbol]["realized"] += realized

    summaries = []
    for label, start, end in periods:
        included = [
            item
            for symbol, item in values[label].items()
            if symbol not in excluded
        ]
        summaries.append(
            PeriodSummary(
                label=label,
                start=start,
                end=end,
                realized_net_pnl=_as_decimal(
                    sum(
                        (item["realized"] for item in included),
                        ZERO,
                    ),
                    field="realized PnL",
                ),
                cash_flow=_as_decimal(
                    sum((item["cash"] for item in included), ZERO),
                    field="cash flow",
                ),
                fees_quote=_as_decimal(
                    sum((item["fees"] for item in included), ZERO),
                    field="fees",
                ),
                fills=sum(int(item["fills"]) for item in included),
                buys=sum(int(item["buys"]) for item in included),
                sells=sum(int(item["sells"]) for item in included),
                fifo_cost=sum((item["fifo_cost"] for item in included), ZERO),
                prior_period_cost=sum((item["prior_cost"] for item in included), ZERO),
                legacy_source=any(item["legacy"] for item in included),
            )
        )
    exclusions = tuple(
        f"{symbol} — {excluded[symbol]}"
        for symbol in sorted(excluded)
    )
    return tuple(summaries), exclusions


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
    ]
    for item in summaries:
        lines.extend(
            (
                "",
                f"{item.label} ({item.start.date()} → {item.end.date()}):",
                f"• Realized FIFO net PnL: {_money(item.realized_net_pnl)}",
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
            "Closed-cycle net PnL: UNAVAILABLE (this ledger does not prove entry-to-exit ownership).",
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


def _last_sent(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("report_date", ""))


def _last_alert(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("blocked_alert_date", ""))


def _mark_state(
    path: Path,
    *,
    report_date: str | None = None,
    blocked_alert_date: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        payload = {}
    if report_date is not None:
        payload["report_date"] = report_date
    if blocked_alert_date is not None:
        payload["blocked_alert_date"] = blocked_alert_date
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
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


if __name__ == "__main__":
    raise SystemExit(main())
