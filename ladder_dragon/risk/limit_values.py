# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: convert exact risk values and publish the effective-limit allowlist.
"""Exact risk conversion and effective-limit reporting."""

from __future__ import annotations

from decimal import Decimal


def money(value: object) -> Decimal:
    """Handle money."""
    return Decimal(str(value or 0))


def status_summary(self) -> dict[str, str | int]:
    """Publish an explicit allowlist from the effective risk limits."""
    return {
        "reserve_usdt": str(self.reserve_usdt),
        "portfolio_cap_usdt": str(self.portfolio_cap_usdt),
        "daily_buy_cap_usdt": str(self.daily_buy_cap_usdt),
        "open_order_count_cap": self.open_order_count_cap,
        "max_daily_loss_usdt": str(self.max_daily_loss_usdt),
        "max_start_drawdown_pct": str(self.max_start_drawdown_pct),
        "max_peak_drawdown_pct": str(self.max_peak_drawdown_pct),
        "max_consecutive_losses": self.max_consecutive_losses,
        "cooldown_sec": self.cooldown_sec,
    }
