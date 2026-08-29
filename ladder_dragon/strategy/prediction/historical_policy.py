# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define immutable, causal inputs for historical entry-policy selection.
"""Strict offline policy inputs and rolling signals without future fill times."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, fields
from decimal import Decimal
import hashlib
import json
import re

from ladder_dragon.strategy.prediction.entry_veto_replay import _ofi_increment, _top

D = Decimal
ZERO = D("0")


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def exact(value, *, positive: bool = True) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("historical financial values must be decimal strings")
    number = D(value)
    if not number.is_finite() or (number <= ZERO if positive else number < ZERO):
        raise ValueError("invalid historical financial value")
    return number


@dataclass(frozen=True)
class HistoricalPolicy:
    symbol: str
    entry_gap_bps: str
    take_profit_bps: str
    stop_trigger_bps: str
    stop_limit_bps: str
    notional_quote: str
    entry_ttl_ms: int
    holding_ms: int
    cadence_ms: int
    latency_ms: int
    cancel_latency_ms: int
    stop_grace_ms: int
    market_impact_bps: str
    maximum_event_gap_ms: int
    allowed_regimes: list[str]
    classifier_fingerprint: str
    panic_source_fingerprint: str
    veto_price_bps: str
    veto_signed_flow: str
    veto_ofi: str
    signal_window_ms: int = 300_000
    maximum_attempts: int = 10_000

    @classmethod
    def parse(cls, payload: dict) -> "HistoricalPolicy":
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("historical policy fields must be explicit and exact")
        policy = cls(**payload)
        if not re.fullmatch(r"[A-Z0-9]{1,20}", policy.symbol):
            raise ValueError("invalid historical symbol")
        for name in ("entry_gap_bps", "take_profit_bps", "stop_trigger_bps",
                     "stop_limit_bps", "notional_quote"):
            exact(getattr(policy, name))
        exact(policy.market_impact_bps, positive=False)
        if not D(policy.stop_trigger_bps) < D(policy.stop_limit_bps) < 10000:
            raise ValueError("historical stop prices are inconsistent")
        if D(policy.entry_gap_bps) >= 10000 or D(policy.market_impact_bps) >= 10000:
            raise ValueError("historical price fractions are invalid")
        for name in ("entry_ttl_ms", "holding_ms", "cadence_ms", "latency_ms",
                     "cancel_latency_ms", "stop_grace_ms", "maximum_event_gap_ms",
                     "signal_window_ms", "maximum_attempts"):
            if type(getattr(policy, name)) is not int or getattr(policy, name) <= 0:
                raise ValueError("historical timing and capacity must be positive integers")
        if not policy.entry_ttl_ms < policy.holding_ms <= 86_400_000:
            raise ValueError("invalid historical holding period")
        if (max(policy.latency_ms, policy.cancel_latency_ms) > 60_000
                or policy.entry_ttl_ms + policy.cancel_latency_ms >= policy.holding_ms):
            raise ValueError("historical transport latency exceeds the observation tail")
        if policy.signal_window_ms > 3_600_000 or policy.maximum_attempts > 10_000:
            raise ValueError("historical replay capacity exceeded")
        if (not isinstance(policy.allowed_regimes, list) or not policy.allowed_regimes
                or len(set(policy.allowed_regimes)) != len(policy.allowed_regimes)
                or not set(policy.allowed_regimes) <= {"RANGE", "TREND_UP", "TREND_DOWN"}):
            raise ValueError("invalid historical executable regimes")
        if not re.fullmatch(r"[a-f0-9]{64}", policy.classifier_fingerprint):
            raise ValueError("missing historical classifier identity")
        if not re.fullmatch(r"[a-f0-9]{64}", policy.panic_source_fingerprint):
            raise ValueError("missing historical PANIC source identity")
        for name in ("veto_price_bps", "veto_signed_flow", "veto_ofi"):
            value = getattr(policy, name)
            if not isinstance(value, str) or not D(value).is_finite() or D(value) >= 0:
                raise ValueError("historical veto thresholds must be negative decimals")
        if min(D(policy.veto_signed_flow), D(policy.veto_ofi)) < -1:
            raise ValueError("historical flow threshold out of range")
        return policy


CONTEXT_FIELDS = {
    "observed_at_ms", "valid_until_ms", "symbol", "classifier_fingerprint",
    "regime", "panic", "tick_size", "step_size", "minimum_quantity",
    "panic_source_fingerprint", "panic_observed_at_ms",
    "minimum_notional_quote", "maker_buy_fee_pct", "maker_sell_fee_pct",
    "taker_buy_fee_pct", "taker_sell_fee_pct", "source_sha256",
}


class HistoricalContext:
    """Use only past, unexpired source attestations, never live fallbacks."""

    def __init__(self, rows: list[dict], policy: HistoricalPolicy, cutoff: int) -> None:
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100_000:
            raise ValueError("historical context is missing or oversized")
        previous = -1
        for row in rows:
            if not isinstance(row, dict) or set(row) != CONTEXT_FIELDS:
                raise ValueError("historical context schema mismatch")
            stamp, until = row["observed_at_ms"], row["valid_until_ms"]
            if (type(stamp) is not int or type(until) is not int
                    or not previous < stamp <= cutoff or until <= stamp):
                raise ValueError("historical context chronology is invalid")
            previous = stamp
            if (
                row["symbol"] != policy.symbol
                or row["classifier_fingerprint"] != policy.classifier_fingerprint
                or row["panic_source_fingerprint"] != policy.panic_source_fingerprint
                or type(row["panic_observed_at_ms"]) is not int
                or not row["observed_at_ms"] - 120_000
                <= row["panic_observed_at_ms"]
                <= row["observed_at_ms"]
            ):
                raise ValueError("historical context identity differs from policy")
            if type(row["panic"]) is not bool or row["regime"] not in {
                "RANGE", "TREND_UP", "TREND_DOWN", "PANIC", "RECOVERY"
            }:
                raise ValueError("invalid historical regime or PANIC state")
            if not re.fullmatch(r"[a-f0-9]{64}", row["source_sha256"]):
                raise ValueError("missing historical context source hash")
            for name in ("tick_size", "step_size", "minimum_quantity", "minimum_notional_quote"):
                exact(row[name])
            for name in ("maker_buy_fee_pct", "maker_sell_fee_pct", "taker_buy_fee_pct", "taker_sell_fee_pct"):
                if exact(row[name], positive=False) >= 1:
                    raise ValueError("historical fee out of range")
        self.rows, self.index = rows, -1

    def at(self, timestamp: int) -> dict:
        while self.index + 1 < len(self.rows) and self.rows[self.index + 1]["observed_at_ms"] <= timestamp:
            self.index += 1
        if self.index < 0 or self.rows[self.index]["valid_until_ms"] <= timestamp:
            raise ValueError("past historical context unavailable")
        return self.rows[self.index]


class RollingVeto:
    """Compute a trailing signal at receive time, without knowing the next fill."""

    def __init__(self, policy: HistoricalPolicy) -> None:
        self.policy = policy
        self.rows = deque()
        self.previous = None
        self.started_at: int | None = None
        self.ofi = self.scale = self.signed = self.volume = ZERO

    def update(self, event) -> bool | None:
        top = _top(event)
        if self.started_at is None:
            self.started_at = event.ts_ms
        increment = _ofi_increment(self.previous, top) if self.previous else ZERO
        self.previous = top
        signed = sum((q if side == "BUY" else -q for _, q, side in event.trades), ZERO)
        volume = sum((q for _, q, _ in event.trades), ZERO)
        self.rows.append((event.ts_ms, top[0], increment, abs(increment), signed, volume))
        self.ofi += increment
        self.scale += abs(increment)
        self.signed += signed
        self.volume += volume
        cutoff = event.ts_ms - self.policy.signal_window_ms
        while len(self.rows) > 1 and self.rows[1][0] <= cutoff:
            _, _, old_ofi, old_scale, old_signed, old_volume = self.rows.popleft()
            self.ofi -= old_ofi
            self.scale -= old_scale
            self.signed -= old_signed
            self.volume -= old_volume
        if len(self.rows) > 100_000:
            raise ValueError("historical signal window capacity reached")
        if self.started_at > cutoff:
            return None
        if not self.volume or not self.scale:
            return False
        return bool(
            (top[0] / self.rows[0][1] - 1) * 10000 <= D(self.policy.veto_price_bps)
            and self.signed / self.volume <= D(self.policy.veto_signed_flow)
            and self.ofi / self.scale <= D(self.policy.veto_ofi)
        )
