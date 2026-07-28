# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: centralize journal states, canonical values and schema version.

"""Order journal schema contracts."""

from decimal import Decimal
import re


ACTIVE_STATES = (
    "PREPARED",
    "UNKNOWN",
    "SUBMITTED",
    "PARTIALLY_FILLED",
    "FILLED",
    "PROTECTION_PENDING",
)
SELL_ACTIVE_STATES = (
    "PREPARED",
    "UNKNOWN",
    "SUBMITTED",
    "PARTIALLY_FILLED",
    "PROTECTED",
)
TERMINAL_EXCHANGE_STATES = {
    "CANCELED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
    "REJECTED",
}
TERMINAL_JOURNAL_STATES = {
    "FILLED",
    "CLOSED",
    "PROTECTED",
    "CANCELED",
    "CANCELLED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
    "REJECTED",
    "FAILED",
}
ORDER_JOURNAL_SCHEMA_VERSION = 3

_SIGNED_BINANCE_URL_RE = re.compile(
    r"(https://(?:[A-Za-z0-9.-]*\.)?binance\.(?:com|vision)/[^\s?]+)\?[^\s;]+",
    re.IGNORECASE,
)
_SIGNATURE_PARAM_RE = re.compile(
    r"(signature=)[^&\s;]+",
    re.IGNORECASE,
)


def decimal_text(value: object, *, field: str) -> str:
    """Return an exact, finite, non-negative canonical decimal string."""
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return format(number, "f")


def price_text(value: object) -> str:
    """Canonicalize a limit price or the non-financial MARKET sentinel."""
    if str(value).upper() == "MARKET":
        return "MARKET"
    return decimal_text(value, field="price")


def safe_error_text(error: object) -> str:
    """Remove signed Binance query data before persisting an error."""
    text = str(error)
    text = _SIGNED_BINANCE_URL_RE.sub(r"\1?<redacted>", text)
    text = _SIGNATURE_PARAM_RE.sub(r"\1<redacted>", text)
    return text[:1000]
