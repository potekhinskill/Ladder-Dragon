# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: persist sanitized order-latency samples for replay calibration.
"""Sanitized correlation between durable order intent and executionReport."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from ladder_dragon.execution.user_stream import OrderStreamSignal


@dataclass(frozen=True)
class ExecutionOutcome:
    """Sanitized actual order outcome used to validate market replay."""

    order_ref: str
    symbol: str
    side: str
    intent_created_at_ms: int
    order_price: Decimal
    original_quantity: Decimal
    cumulative_quantity: Decimal
    cumulative_quote: Decimal
    final_status: str
    first_fill_received_at_ms: int | None
    final_received_at_ms: int
    commission_quote: Decimal | None = None

    @property
    def fill_ratio(self) -> Decimal:
        if self.original_quantity <= 0:
            return Decimal("0")
        return min(
            Decimal("1"), self.cumulative_quantity / self.original_quantity
        )

    @property
    def average_fill_price(self) -> Decimal | None:
        if self.cumulative_quantity <= 0:
            return None
        return self.cumulative_quote / self.cumulative_quantity


def _exact_nonnegative(value: object, *, field: str) -> str:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return format(result, "f")


def append_execution_latency_sample(
    path: str | Path,
    signal: OrderStreamSignal,
    *,
    intent_created_at_ms: int,
    commission_quote: Decimal | None = None,
    commission_value_status: str = "not_applicable",
) -> dict[str, object]:
    """Append one non-secret timing sample with a hashed client identity."""
    created = int(intent_created_at_ms)
    received = int(signal.received_time_ms)
    if created <= 0 or received < created:
        raise ValueError("execution latency timestamps are invalid")
    payload: dict[str, object] = {
        "schema_version": 3,
        "symbol": signal.symbol,
        "order_ref": hashlib.sha256(
            f"{signal.symbol}:{signal.order_id}:{signal.client_order_id}".encode()
        ).hexdigest()[:24],
        "intent_created_at_ms": created,
        "event_time_ms": int(signal.event_time_ms),
        "transaction_time_ms": int(signal.transaction_time_ms),
        "received_at_ms": received,
        "execution_type": signal.execution_type,
        "trade_id": signal.trade_id,
        "order_status": signal.order_status,
        "side": signal.side,
        "order_price": _exact_nonnegative(signal.order_price, field="order price"),
        "original_quantity": _exact_nonnegative(
            signal.original_quantity, field="original quantity"
        ),
        "last_price": _exact_nonnegative(signal.last_price, field="last price"),
        "last_quantity": _exact_nonnegative(
            signal.last_quantity, field="last quantity"
        ),
        "cumulative_quantity": _exact_nonnegative(
            signal.cumulative_quantity, field="cumulative quantity"
        ),
        "cumulative_quote": _exact_nonnegative(
            signal.cumulative_quote, field="cumulative quote"
        ),
        "commission_quote": (
            _exact_nonnegative(commission_quote, field="commission quote")
            if commission_quote is not None else None
        ),
        "commission_value_status": str(commission_value_status)[:32],
        "intent_to_event_ms": max(0, int(signal.event_time_ms) - created),
        "intent_to_receive_ms": received - created,
        "exchange_to_receive_ms": (
            max(0, received - int(signal.event_time_ms))
            if signal.event_time_ms > 0 else None
        ),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(
        target,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, line.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return payload


def load_execution_latencies(path: str | Path) -> list[int]:
    """Load local pre-POST-to-NEW-report latency from sanitized JSONL."""
    values: list[int] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise ValueError(f"latency line {line_number} is not an object")
            if int(payload.get("schema_version", 0)) not in {1, 2, 3}:
                raise ValueError(f"latency line {line_number} has unsupported schema")
            if (
                str(payload.get("execution_type", "")).upper() != "NEW"
                or str(payload.get("order_status", "")).upper() != "NEW"
            ):
                continue
            value = int(payload.get("intent_to_receive_ms", -1))
            if value < 0 or value > 300_000:
                raise ValueError(f"latency line {line_number} is out of range")
            values.append(value)
    return values


def load_execution_outcomes(path: str | Path) -> list[ExecutionOutcome]:
    """Group sanitized execution reports into exact order outcomes."""
    grouped: dict[str, dict[str, object]] = {}
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise ValueError(f"outcome line {line_number} is not an object")
            schema_version = int(payload.get("schema_version", 0))
            if schema_version not in {2, 3}:
                continue
            order_ref = str(payload.get("order_ref", ""))
            if not order_ref:
                raise ValueError(f"outcome line {line_number} has no order reference")
            original = Decimal(str(payload.get("original_quantity", "0")))
            cumulative = Decimal(str(payload.get("cumulative_quantity", "0")))
            quote = Decimal(str(payload.get("cumulative_quote", "0")))
            order_price = Decimal(str(payload.get("order_price", "0")))
            if any(
                not value.is_finite() or value < 0
                for value in (original, cumulative, quote, order_price)
            ):
                raise ValueError(f"outcome line {line_number} has invalid values")
            current = grouped.setdefault(
                order_ref,
                {
                    "order_ref": order_ref,
                    "symbol": str(payload.get("symbol", "")).upper(),
                    "side": str(payload.get("side", "")).upper(),
                    "intent_created_at_ms": int(
                        payload.get("intent_created_at_ms", 0)
                    ),
                    "order_price": order_price,
                    "original_quantity": original,
                    "cumulative_quantity": Decimal("0"),
                    "cumulative_quote": Decimal("0"),
                    "final_status": "",
                    "commission_quote": (
                        Decimal("0") if schema_version >= 3 else None
                    ),
                    "commission_trade_ids": set(),
                    "first_fill_received_at_ms": None,
                    "final_received_at_ms": 0,
                },
            )
            if (
                current["symbol"] != str(payload.get("symbol", "")).upper()
                or current["side"] != str(payload.get("side", "")).upper()
                or current["order_price"] != order_price
                or current["original_quantity"] != original
            ):
                raise ValueError(f"outcome line {line_number} changes order identity")
            if cumulative >= current["cumulative_quantity"]:
                current["cumulative_quantity"] = cumulative
                current["cumulative_quote"] = quote
                current["final_status"] = str(
                    payload.get("order_status", "")
                ).upper()
                current["final_received_at_ms"] = int(
                    payload.get("received_at_ms", 0)
                )
            if (
                schema_version >= 3
                and str(payload.get("execution_type", "")).upper() == "TRADE"
            ):
                trade_id = int(payload.get("trade_id", -1))
                status = str(
                    payload.get("commission_value_status", "")
                ).lower()
                raw_fee = payload.get("commission_quote")
                if trade_id < 0 or status not in {"exact", "converted", "quote"}:
                    current["commission_quote"] = None
                elif raw_fee is None:
                    current["commission_quote"] = None
                elif (
                    current["commission_quote"] is not None
                    and trade_id not in current["commission_trade_ids"]
                ):
                    fee = Decimal(str(raw_fee))
                    if not fee.is_finite() or fee < 0:
                        raise ValueError(
                            f"outcome line {line_number} has invalid commission"
                        )
                    current["commission_quote"] += fee
                    current["commission_trade_ids"].add(trade_id)
            if (
                cumulative > 0
                and current["first_fill_received_at_ms"] is None
            ):
                current["first_fill_received_at_ms"] = int(
                    payload.get("received_at_ms", 0)
                )
    outcomes = []
    for values in grouped.values():
        values.pop("commission_trade_ids", None)
        if (
            values["intent_created_at_ms"] <= 0
            or values["order_price"] <= 0
            or values["original_quantity"] <= 0
            or values["side"] not in {"BUY", "SELL"}
            or values["final_received_at_ms"] <= 0
        ):
            continue
        outcomes.append(ExecutionOutcome(**values))
    return sorted(outcomes, key=lambda item: item.intent_created_at_ms)
