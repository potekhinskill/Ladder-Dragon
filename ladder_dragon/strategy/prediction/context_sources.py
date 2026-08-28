# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate minimal historical filter, fee, and runtime attestations.
"""Source-owned, secret-free observations for historical selection only."""

from __future__ import annotations

from decimal import Decimal
import re

from ladder_dragon.strategy.prediction.historical_policy import exact, fingerprint
from ladder_dragon.strategy.prediction.episode_semantics import require_execution_regime_contract

SOURCE_TTL_MS = 300_000
RUNTIME_TTL_MS = 180_000
FILTER_FIELDS = {"tick_size", "step_size", "minimum_quantity", "minimum_notional_quote"}
FEE_FIELDS = {"maker_buy_fee_pct", "maker_sell_fee_pct", "taker_buy_fee_pct", "taker_sell_fee_pct"}
KINDS = {"filters": "BINANCE_EXCHANGE_INFO_V1", "fees": "BINANCE_ACCOUNT_COMMISSION_MAX_V1",
         "runtime": "SUPERVISOR_CONSUMED_REGIME_PANIC_V1"}


def symbol_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{5,20}", value):
        raise ValueError("invalid context symbol")
    return value


def stamp(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid context timestamp")
    return value


def attest(kind: str, symbol: str, observed_at_ms: int, values: dict) -> dict:
    """Hash a narrow projection, never the remote response or its headers."""
    body = {"kind": KINDS[kind], "symbol": symbol_name(symbol),
            "observed_at_ms": stamp(observed_at_ms),
            "valid_until_ms": observed_at_ms + (RUNTIME_TTL_MS if kind == "runtime" else SOURCE_TTL_MS),
            "values": values}
    result = dict(body, sha256=fingerprint(body))
    validate_source(kind, result)
    return result


def validate_source(kind: str, source: dict) -> None:
    if not isinstance(source, dict) or set(source) != {
        "kind", "symbol", "observed_at_ms", "valid_until_ms", "values", "sha256"
    }:
        raise ValueError("context source schema differs")
    symbol_name(source["symbol"])
    duration = stamp(source["valid_until_ms"]) - stamp(source["observed_at_ms"])
    ceiling = RUNTIME_TTL_MS if kind == "runtime" else SOURCE_TTL_MS
    if source["kind"] != KINDS[kind] or not 0 < duration <= ceiling:
        raise ValueError("context source lifetime differs")
    if fingerprint({k: v for k, v in source.items() if k != "sha256"}) != source["sha256"]:
        raise ValueError("context source hash differs")
    values = source["values"]
    if not isinstance(values, dict):
        raise ValueError("context source values missing")
    if kind in {"filters", "fees"}:
        if set(values) != (FILTER_FIELDS if kind == "filters" else FEE_FIELDS):
            raise ValueError("context financial fields differ")
        for value in values.values():
            number = exact(value, positive=kind == "filters")
            if kind == "fees" and number >= 1:
                raise ValueError("context commission out of range")
    else:
        if set(values) != {"classifier", "regime", "panic", "panic_hits"}:
            raise ValueError("context runtime fields differ")
        require_execution_regime_contract(values["classifier"])
        if values["regime"] not in {"RANGE", "TREND_UP", "TREND_DOWN", "PANIC", "RECOVERY"}:
            raise ValueError("context regime invalid")
        if type(values["panic"]) is not bool or type(values["panic_hits"]) is not int:
            raise ValueError("context PANIC unavailable")
        if not 0 <= values["panic_hits"] <= 1_000_000:
            raise ValueError("context PANIC hits invalid")


def filter_source(symbol: str, payload: dict, observed_at_ms: int) -> dict:
    """Accept one identified trading symbol and exact required filters."""
    rows = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get("symbol") != symbol:
        raise ValueError("context exchange symbol mismatch")
    info = rows[0]
    if info.get("status") != "TRADING" or not isinstance(info.get("filters"), list):
        raise ValueError("context exchange filters unavailable")
    entries = info["filters"]
    if not all(isinstance(item, dict) for item in entries):
        raise ValueError("context exchange filters invalid")
    by_type = {item.get("filterType"): item for item in entries}
    if len(by_type) != len(entries):
        raise ValueError("context exchange filters duplicate")
    notionals = [by_type[name]["minNotional"] for name in ("MIN_NOTIONAL", "NOTIONAL") if name in by_type]
    if not notionals:
        raise ValueError("context notional filter missing")
    return attest("filters", symbol, observed_at_ms, {
        "tick_size": by_type["PRICE_FILTER"]["tickSize"],
        "step_size": by_type["LOT_SIZE"]["stepSize"],
        "minimum_quantity": by_type["LOT_SIZE"]["minQty"],
        "minimum_notional_quote": str(max(exact(value) for value in notionals)),
    })


def fee_source(symbol: str, payload: dict, observed_at_ms: int) -> dict:
    """Keep undiscounted rates; absent tax or special fields are not zero."""
    if not isinstance(payload, dict) or payload.get("symbol") != symbol:
        raise ValueError("context commission symbol mismatch")
    sections = [payload[name] for name in ("standardCommission", "taxCommission", "specialCommission")]
    rates = {}
    for role in ("maker", "taker"):
        for side, field in (("buy", "buyer"), ("sell", "seller")):
            total = sum((exact(section[role], positive=False) + exact(section[field], positive=False)
                         for section in sections), Decimal("0"))
            rates[f"{role}_{side}_fee_pct"] = str(total)
    return attest("fees", symbol, observed_at_ms, rates)


def context_from_sources(sources: dict, observed_at_ms: int) -> dict:
    """Never backdate an observation to a candle close or a request start."""
    if not isinstance(sources, dict) or set(sources) != set(KINDS):
        raise ValueError("context source bundle incomplete")
    for kind, source in sources.items():
        validate_source(kind, source)
        if not source["observed_at_ms"] <= stamp(observed_at_ms) < source["valid_until_ms"]:
            raise ValueError("context source expired or future")
    if len({source["symbol"] for source in sources.values()}) != 1:
        raise ValueError("context source symbols differ")
    runtime = sources["runtime"]["values"]
    return {"observed_at_ms": observed_at_ms,
            "valid_until_ms": min(source["valid_until_ms"] for source in sources.values()),
            "symbol": sources["runtime"]["symbol"],
            "classifier_fingerprint": fingerprint(runtime["classifier"]),
            "regime": runtime["regime"], "panic": runtime["panic"],
            **sources["filters"]["values"], **sources["fees"]["values"],
            "source_sha256": fingerprint(sources)}
