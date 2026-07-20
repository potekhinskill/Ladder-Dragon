# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: report whether legacy runtime and accounting compatibility can retire.
"""Read-only compatibility retirement audit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterable


@dataclass(frozen=True)
class CompatibilityAudit:
    ready_for_major_removal: bool
    reasons: tuple[str, ...]
    legacy_paths: tuple[str, ...]
    missing_exact_trades: int
    missing_exact_inventory: int

    def as_dict(self) -> dict[str, object]:
        return {
            "ready_for_major_removal": self.ready_for_major_removal,
            "reasons": list(self.reasons),
            "legacy_paths": list(self.legacy_paths),
            "missing_exact_trades": self.missing_exact_trades,
            "missing_exact_inventory": self.missing_exact_inventory,
        }


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def audit_compatibility(
    database: Path,
    *,
    legacy_paths: Iterable[Path] = (),
) -> CompatibilityAudit:
    reasons: list[str] = []
    present_paths = tuple(
        sorted(str(path) for path in legacy_paths if path.exists())
    )
    if present_paths:
        reasons.append("legacy configuration or service paths still exist")
    missing_trades = 0
    missing_inventory = 0
    if not database.is_file():
        reasons.append("statistics database is unavailable")
    else:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            trade_columns = _table_columns(connection, "trades")
            inventory_columns = _table_columns(connection, "inventory")
            required_trade = {"price_text", "gross_qty", "net_qty"}
            required_inventory = {
                "qty_text", "avg_cost_text", "realized_pnl_text",
            }
            if not required_trade <= trade_columns:
                reasons.append("trades exact-text schema is incomplete")
            else:
                missing_trades = int(connection.execute(
                    "SELECT COUNT(*) FROM trades WHERE "
                    "NULLIF(price_text,'') IS NULL OR "
                    "NULLIF(gross_qty,'') IS NULL OR "
                    "NULLIF(net_qty,'') IS NULL"
                ).fetchone()[0])
                if missing_trades:
                    reasons.append("trade rows are missing exact-text values")
            if not required_inventory <= inventory_columns:
                reasons.append("inventory exact-text schema is incomplete")
            else:
                missing_inventory = int(connection.execute(
                    "SELECT COUNT(*) FROM inventory WHERE "
                    "NULLIF(qty_text,'') IS NULL OR "
                    "NULLIF(avg_cost_text,'') IS NULL OR "
                    "NULLIF(realized_pnl_text,'') IS NULL"
                ).fetchone()[0])
                if missing_inventory:
                    reasons.append("inventory rows are missing exact-text values")
    return CompatibilityAudit(
        ready_for_major_removal=not reasons,
        reasons=tuple(reasons),
        legacy_paths=present_paths,
        missing_exact_trades=missing_trades,
        missing_exact_inventory=missing_inventory,
    )
