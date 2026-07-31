# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: normalize host telemetry values without shell access.

"""Host telemetry and read-only chart-series helpers."""

import json
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def bounded_percent(value: object) -> float:
    """Clamp presentation telemetry into the conventional percent range."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, max(0.0, parsed))


def load_history_payload(
    history_file: Path,
    *,
    cutoff_epoch: int,
    points: int,
    timezone,
) -> dict[str, Any]:
    """Load bounded host samples and retain epochs for aligned trade charts."""
    rows: list[dict[str, Any]] = []
    try:
        with history_file.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                    if int(item.get("ts", 0)) >= cutoff_epoch:
                        rows.append(item)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    rows.sort(key=lambda item: int(item.get("ts", 0)))
    if len(rows) > points and points > 0:
        step = max(1, len(rows) // points)
        rows = rows[::step]
    epochs = [int(item["ts"]) for item in rows]
    return {
        "labels": [
            datetime.fromtimestamp(epoch, timezone).strftime("%H:%M")
            for epoch in epochs
        ],
        "temp_c": [item.get("temp_c") for item in rows],
        "mem_used_gib": [item.get("mem_used_gib") for item in rows],
        "cpu_pct": [item.get("cpu_pct") for item in rows],
        "_epochs": epochs,
    }


def rolling_trade_volume_24h_usdt(
    connection: sqlite3.Connection,
    sample_epochs: list[int],
) -> list[str]:
    """Return exact BUY+SELL quote turnover for each trailing 24-hour window."""
    if not sample_epochs:
        return []
    earliest = min(sample_epochs) - 86_400
    latest = max(sample_epochs)
    rows = connection.execute(
        """
        SELECT
          CASE WHEN ts>1000000000000
               THEN CAST(ts/1000 AS INTEGER)
               ELSE CAST(ts AS INTEGER) END AS ts_s,
          price_text AS price,
          gross_qty_text AS qty
        FROM trades_exact
        WHERE UPPER(side) IN ('BUY', 'SELL')
          AND (CASE WHEN ts>1000000000000
                    THEN CAST(ts/1000 AS INTEGER)
                    ELSE CAST(ts AS INTEGER) END) > ?
          AND (CASE WHEN ts>1000000000000
                    THEN CAST(ts/1000 AS INTEGER)
                    ELSE CAST(ts AS INTEGER) END) <= ?
        ORDER BY ts_s ASC
        """,
        (earliest, latest),
    ).fetchall()
    trades: list[tuple[int, Decimal]] = []
    for row in rows:
        try:
            price = Decimal(str(row["price"]))
            quantity = Decimal(str(row["qty"]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("invalid exact trade amount") from exc
        if not price.is_finite() or not quantity.is_finite() or price < 0 or quantity < 0:
            raise ValueError("invalid exact trade amount")
        trades.append((int(row["ts_s"]), price * quantity))

    values: list[str] = []
    left = 0
    right = 0
    running = Decimal("0")
    for sample_epoch in sample_epochs:
        while right < len(trades) and trades[right][0] <= sample_epoch:
            running += trades[right][1]
            right += 1
        cutoff = sample_epoch - 86_400
        while left < right and trades[left][0] <= cutoff:
            running -= trades[left][1]
            left += 1
        values.append(format(running, "f"))
    return values
