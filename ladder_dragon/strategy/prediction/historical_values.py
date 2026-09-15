# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate finite Decimal values used by historical selection.
"""Finite Decimal validation for historical selection evidence."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"historical {field} is invalid") from exc
    if not number.is_finite():
        raise ValueError(f"historical {field} is invalid")
    return number
