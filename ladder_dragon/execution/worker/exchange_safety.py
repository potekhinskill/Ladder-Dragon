# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: stop execution when a safety lookup cannot establish order state.

"""Fail-closed worker exchange lookup boundaries."""

from __future__ import annotations

from typing import Any, Callable

import requests


def require_order_status(
    symbol: str,
    order_id: int,
    get_order: Callable[[str, int], dict[str, Any] | None],
    halt: Callable[..., None],
    reason: str,
) -> dict[str, Any] | None:
    """Return one order status or enter HALT and raise a safe error."""
    try:
        return get_order(symbol, order_id)
    except (
        requests.RequestException,
        RuntimeError,
        ValueError,
        ArithmeticError,
        OSError,
    ) as exc:
        halt(
            reason,
            symbol=symbol,
            order_id=order_id,
            error_type=type(exc).__name__,
        )
        raise RuntimeError(reason) from exc
