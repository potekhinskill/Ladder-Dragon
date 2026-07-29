# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate exact account quantities used by protection services.
"""Exact validation shared by position-protection services."""

from decimal import Decimal
from typing import Dict


def exact_balance_quantity(
    balances: Dict[str, Dict[str, object]], asset: str, field: str
) -> Decimal:
    """Return a finite non-negative account balance quantity."""
    value = Decimal(str((balances.get(asset) or {}).get(field, 0) or 0))
    if not value.is_finite() or value < 0:
        raise ValueError(f"invalid {asset} {field} balance")
    return value
