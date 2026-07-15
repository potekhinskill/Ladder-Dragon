"""Deterministic Binance client-order identifiers for retry idempotency."""

from __future__ import annotations

import hashlib
import time


def client_order_id(
    symbol: str,
    side: str,
    purpose: str,
    price: object,
    qty: object,
    *,
    bucket_seconds: int = 300,
    now: float | None = None,
) -> str:
    bucket = int((now or time.time()) // max(1, bucket_seconds))
    intent = f"{symbol.upper()}|{side.upper()}|{purpose}|{price}|{qty}|{bucket}"
    digest = hashlib.blake2s(intent.encode("utf-8"), digest_size=9).hexdigest()
    prefix = f"LD{side[:1].upper()}{purpose[:3].upper()}"
    return f"{prefix}-{digest}"[:36]
