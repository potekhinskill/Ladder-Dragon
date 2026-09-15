# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: settle partial BUY exposure before sizing its protection.
"""Cancel only the verified entry remainder and re-read terminal quantity."""

from decimal import Decimal

import requests

from ladder_dragon.execution.order_recovery import TERMINAL_EXCHANGE_STATES


def settle_partial_entry(symbol, order_id, order, *, cancel, get_order, logger):
    """Never size protection from a cancel acknowledgement or stale fill."""
    def quantity(payload):
        if (not isinstance(payload, dict) or payload.get("symbol") != symbol
                or payload.get("side") != "BUY"
                or type(payload.get("orderId")) is not int
                or payload["orderId"] != order_id):
            raise ValueError("partial BUY identity mismatch")
        original = Decimal(str(payload.get("origQty")))
        filled = Decimal(str(payload.get("executedQty")))
        if (not original.is_finite() or not filled.is_finite()
                or not 0 < filled <= original):
            raise ValueError("partial BUY quantity invalid")
        return original, filled

    original, before = quantity(order)
    if cancel is None:
        raise RuntimeError("partial BUY cancellation unavailable")
    try:
        cancel(symbol, order_id)
    except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
        # A timeout cannot prove rejection. Only the following read settles it.
        logger(f"[PARTIAL-CANCEL] verification required error={type(exc).__name__}")
    final = get_order(symbol, order_id)
    final_original, after = quantity(final)
    if (final_original != original or after < before
            or final.get("status") not in set(TERMINAL_EXCHANGE_STATES) | {"FILLED"}
            or (final.get("status") == "FILLED" and after != original)):
        raise ValueError("partial BUY cancellation is not terminal and monotonic")
    return final
