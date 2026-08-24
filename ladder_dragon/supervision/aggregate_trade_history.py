# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: read complete bounded Binance aggregate-trade windows.
"""Bounded pagination for one closed aggregate-trade interval."""

from __future__ import annotations

from typing import Callable, Mapping
from urllib.parse import urlsplit


PublicGet = Callable[[str, Mapping[str, object]], object]


def safe_aggregate_trade_error(error: BaseException) -> str:
    """Return bounded Binance fields without provider text or query data."""
    error_type = type(error).__name__
    if error_type != "BinanceHttpError":
        return error_type
    fields = [error_type]
    for name, label in (("status", "status"), ("code", "code")):
        value = getattr(error, name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            fields.append(f"{label}={value}")
    raw_endpoint = str(getattr(error, "endpoint", "") or "")
    endpoint = urlsplit(raw_endpoint).path[:128]
    if endpoint.startswith("/") and all(
        char.isascii() and (char.isalnum() or char in "/._-")
        for char in endpoint
    ):
        fields.append(f"endpoint={endpoint}")
    retry_after = getattr(error, "retry_after_seconds", None)
    if (
        isinstance(retry_after, int)
        and not isinstance(retry_after, bool)
        and 0 <= retry_after <= 259_200
    ):
        fields.append(f"retry_after={retry_after}s")
    return " ".join(fields)


def load_aggregate_trade_window(
    public_get: PublicGet,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    maximum_pages: int = 8,
) -> tuple[list[dict[str, object]], bool, int]:
    """Load one interval and fail closed on gaps or pagination exhaustion."""
    if start_ms < 0 or end_ms <= start_ms or not 1 <= maximum_pages <= 32:
        raise ValueError("aggregate trade window is invalid")
    output: list[dict[str, object]] = []
    previous_id: int | None = None
    pages = 0
    from_id: int | None = None
    while pages < maximum_pages:
        params: dict[str, object] = {"symbol": symbol.upper(), "limit": 1000}
        if from_id is None:
            params["startTime"] = start_ms
            params["endTime"] = end_ms
        else:
            # Binance rejects fromId combined with the time-range parameters.
            params["fromId"] = from_id
        raw = public_get("/api/v3/aggTrades", params)
        if not isinstance(raw, list):
            raise ValueError("aggregate trade page is unavailable")
        pages += 1
        page: list[dict[str, object]] = []
        crossed_end = False
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError("aggregate trade row is invalid")
            row = dict(item)
            trade_id = int(row.get("a", -1))
            timestamp = int(row.get("T", -1))
            if trade_id < 0 or timestamp < 0:
                raise ValueError("aggregate trade identity is invalid")
            if previous_id is not None and trade_id != previous_id + 1:
                raise ValueError("aggregate trade sequence is incomplete")
            previous_id = trade_id
            if timestamp > end_ms:
                crossed_end = True
                break
            if start_ms < timestamp <= end_ms:
                page.append(row)
        output.extend(page)
        if crossed_end:
            return output, True, pages
        if len(raw) < 1000:
            return output, True, pages
        if previous_id is None:
            raise ValueError("aggregate trade page cannot advance")
        from_id = previous_id + 1
    return output, False, pages


__all__ = ["load_aggregate_trade_window", "safe_aggregate_trade_error"]
