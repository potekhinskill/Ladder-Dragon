"""Deterministic Binance client-order identifiers for retry idempotency."""

from __future__ import annotations

import hashlib
import os
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
    # Короткий тег decision сохраняет трассировку AI в Binance clientOrderId,
    # не раскрывая полный внутренний UUID в публичном идентификаторе.
    decision_tag = os.getenv("BOT_AI_DECISION_ID", "").strip()[:8]
    intent = f"{symbol.upper()}|{side.upper()}|{purpose}|{price}|{qty}|{bucket}|{decision_tag}"
    digest = hashlib.blake2s(intent.encode("utf-8"), digest_size=9).hexdigest()
    prefix = f"LD{side[:1].upper()}{purpose[:3].upper()}" + (f"-{decision_tag[:6]}" if decision_tag else "")
    return f"{prefix}-{digest}"[:36]
