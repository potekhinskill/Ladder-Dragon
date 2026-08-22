# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: read complete bounded Binance aggregate-trade windows.
"""Bounded pagination for one closed aggregate-trade interval."""

from __future__ import annotations

from typing import Callable, Mapping


PublicGet = Callable[[str, Mapping[str, object]], object]


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
        params: dict[str, object] = {
            "symbol": symbol.upper(),
            "endTime": end_ms,
            "limit": 1000,
        }
        if from_id is None:
            params["startTime"] = start_ms
        else:
            params["fromId"] = from_id
        raw = public_get("/api/v3/aggTrades", params)
        if not isinstance(raw, list):
            raise ValueError("aggregate trade page is unavailable")
        pages += 1
        page: list[dict[str, object]] = []
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
            if start_ms < timestamp <= end_ms:
                page.append(row)
        output.extend(page)
        if len(raw) < 1000:
            return output, True, pages
        if previous_id is None:
            raise ValueError("aggregate trade page cannot advance")
        from_id = previous_id + 1
    return output, False, pages


__all__ = ["load_aggregate_trade_window"]
