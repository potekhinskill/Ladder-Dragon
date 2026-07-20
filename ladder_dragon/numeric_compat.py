# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: isolate finite float conversion for indicator and JSON compatibility.
"""Explicit numeric compatibility boundary for non-authoritative analytics."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math


def compatibility_float(
    value: object, *, field: str = "compatibility number"
) -> float:
    """Return one finite binary float only for an external numeric boundary.

    Financial state must remain Decimal or exact text. This helper exists for
    indicator libraries, timestamps and legacy JSON consumers that explicitly
    require a binary floating-point value.
    """
    try:
        exact = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc
    if not exact.is_finite():
        raise ValueError(f"{field} must be finite")
    converted = float(exact)
    if not math.isfinite(converted):
        raise ValueError(f"{field} is outside the compatibility range")
    return converted
