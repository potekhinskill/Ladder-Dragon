# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: fetch bounded public Binance candles without credentials.
"""Bounded public market-data transport for scenario analysis."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from typing import Any

import requests

from ladder_dragon.strategy.scenario_analysis import ScenarioBar


MAX_RESPONSE_BYTES = 512 * 1024


class PublicMarketDataError(RuntimeError):
    """Report a bounded public-data failure without response text."""

    def __init__(self, *, endpoint: str, status: int | None) -> None:
        self.endpoint = endpoint
        self.status = status
        suffix = f" status={status}" if status is not None else ""
        super().__init__(f"public market data unavailable endpoint={endpoint}{suffix}")


def _payload(response: requests.Response, endpoint: str) -> Any:
    chunks: list[bytes] = []
    size = 0
    try:
        for chunk in response.iter_content(chunk_size=8192):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise PublicMarketDataError(
                    endpoint=endpoint, status=response.status_code
                )
            chunks.append(chunk)
        return json.loads(b"".join(chunks).decode("utf-8"))
    except PublicMarketDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PublicMarketDataError(
            endpoint=endpoint, status=response.status_code
        ) from exc


def fetch_closed_klines(
    session: requests.Session,
    *,
    base_url: str,
    symbol: str,
    timeframe: str,
    now_ms: int,
    limit: int = 120,
    timeout_sec: float = 10.0,
) -> tuple[ScenarioBar, ...]:
    """Fetch closed public candles and reject malformed provider data."""
    endpoint = "/api/v3/klines"
    try:
        response = session.get(
            f"{base_url.rstrip('/')}{endpoint}",
            params={"symbol": symbol, "interval": timeframe, "limit": limit},
            timeout=timeout_sec,
            stream=True,
        )
    except requests.RequestException as exc:
        raise PublicMarketDataError(endpoint=endpoint, status=None) from exc
    payload = _payload(response, endpoint)
    if response.status_code >= 400 or not isinstance(payload, list):
        raise PublicMarketDataError(endpoint=endpoint, status=response.status_code)
    bars = []
    try:
        for row in payload:
            if not isinstance(row, list) or len(row) < 7:
                raise ValueError("invalid kline row")
            close_time = int(row[6])
            if close_time >= now_ms:
                continue
            bars.append(ScenarioBar(
                open_time_ms=int(row[0]),
                close_time_ms=close_time,
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
            ))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PublicMarketDataError(
            endpoint=endpoint, status=response.status_code
        ) from exc
    return tuple(bars)
