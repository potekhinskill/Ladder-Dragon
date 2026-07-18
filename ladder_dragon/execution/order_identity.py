# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the order identity component of the execution layer.
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
    # A short decision tag keeps AI traceability in Binance clientOrderId
    # without exposing the full internal UUID in a public identifier.
    decision_tag = os.getenv("BOT_AI_DECISION_ID", "").strip()[:8]
    intent = f"{symbol.upper()}|{side.upper()}|{purpose}|{price}|{qty}|{bucket}|{decision_tag}"
    digest = hashlib.blake2s(intent.encode("utf-8"), digest_size=9).hexdigest()
    prefix = f"LD{side[:1].upper()}{purpose[:3].upper()}" + (f"-{decision_tag[:6]}" if decision_tag else "")
    return f"{prefix}-{digest}"[:36]
