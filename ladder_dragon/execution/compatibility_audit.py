# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: report whether legacy runtime and accounting compatibility can retire.
"""Read-only compatibility retirement audit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterable


DEFAULT_LEGACY_PATHS = (
    Path("/etc/bot-alerts.env"),
    Path("/etc/systemd/system/ai-supervisor.service"),
    Path("/etc/systemd/system/binance-bot.service"),
    Path("/etc/nginx/sites-available/pi-dashboard"),
    Path("/etc/nginx/sites-enabled/pi-dashboard"),
    Path("/opt/pi-dashboard"),
)


@dataclass(frozen=True)
class CompatibilityAudit:
    ready_for_major_removal: bool
    reasons: tuple[str, ...]
    legacy_paths: tuple[str, ...]
    missing_exact_trades: int
    missing_exact_inventory: int
    legacy_commission_rows: int
    legacy_trade_real_columns: tuple[str, ...]
    legacy_inventory_real_columns: tuple[str, ...]
    legacy_sync_objects: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ready_for_major_removal": self.ready_for_major_removal,
            "reasons": list(self.reasons),
            "legacy_paths": list(self.legacy_paths),
            "missing_exact_trades": self.missing_exact_trades,
            "missing_exact_inventory": self.missing_exact_inventory,
            "legacy_commission_rows": self.legacy_commission_rows,
            "legacy_trade_real_columns": list(self.legacy_trade_real_columns),
            "legacy_inventory_real_columns": list(self.legacy_inventory_real_columns),
            "legacy_sync_objects": list(self.legacy_sync_objects),
            "sqlite_retirement_required": bool(
                self.legacy_trade_real_columns
                or self.legacy_inventory_real_columns
                or self.legacy_sync_objects
            ),
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
    legacy_commissions = 0
    trade_real_columns: tuple[str, ...] = ()
    inventory_real_columns: tuple[str, ...] = ()
    sync_objects: tuple[str, ...] = ()
    if not database.is_file():
        reasons.append("statistics database is unavailable")
    else:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            trade_columns = _table_columns(connection, "trades")
            inventory_columns = _table_columns(connection, "inventory")
            trade_real_columns = tuple(sorted(
                {"price", "qty", "fee_quote"} & trade_columns
            ))
            inventory_real_columns = tuple(sorted(
                {"qty", "avg_cost", "realized_pnl"} & inventory_columns
            ))
            sync_objects = tuple(sorted(
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name IN ('trades_exact_after_insert',"
                    "'inventory_exact_after_insert',"
                    "'inventory_exact_after_legacy_update')"
                )
            ))
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
                if "commission_value_status" not in trade_columns:
                    reasons.append("trade commission provenance is unavailable")
                else:
                    legacy_commissions = int(connection.execute(
                        "SELECT COUNT(*) FROM trades WHERE "
                        "LOWER(COALESCE(commission_value_status,'')) "
                        "IN ('','legacy','unpriced')"
                    ).fetchone()[0])
                    if legacy_commissions:
                        reasons.append(
                            "trade rows still have legacy or unpriced commissions"
                        )
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
        legacy_commission_rows=legacy_commissions,
        legacy_trade_real_columns=trade_real_columns,
        legacy_inventory_real_columns=inventory_real_columns,
        legacy_sync_objects=sync_objects,
    )
