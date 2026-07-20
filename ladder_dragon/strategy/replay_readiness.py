# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: audit multi-archive replay calibration readiness.
"""Fail-closed readiness checks for empirical replay calibration data."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from ladder_dragon.strategy.market_replay import ReplayCalibration


@dataclass(frozen=True)
class ReplayReadiness:
    ready: bool
    reasons: tuple[str, ...]
    archive_count: int
    span_days: Decimal
    regimes: tuple[str, ...]
    measured_latency_archives: int
    execution_sample_count: int
    book_event_count: int
    trade_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "reasons": list(self.reasons),
            "archive_count": self.archive_count,
            "span_days": format(self.span_days, "f"),
            "regimes": list(self.regimes),
            "measured_latency_archives": self.measured_latency_archives,
            "execution_sample_count": self.execution_sample_count,
            "book_event_count": self.book_event_count,
            "trade_count": self.trade_count,
        }


def volatility_regime(
    volatility_bps: Decimal,
    *,
    low_max_bps: Decimal = Decimal("0.5"),
    high_min_bps: Decimal = Decimal("2"),
) -> str:
    if not volatility_bps.is_finite() or volatility_bps < 0:
        raise ValueError("volatility must be finite and non-negative")
    if low_max_bps < 0 or high_min_bps <= low_max_bps:
        raise ValueError("volatility regime thresholds are invalid")
    if volatility_bps <= low_max_bps:
        return "low"
    if volatility_bps >= high_min_bps:
        return "high"
    return "normal"


def audit_replay_readiness(
    calibrations: Iterable[ReplayCalibration],
    *,
    minimum_archives: int = 3,
    minimum_span_days: Decimal = Decimal("2"),
    required_regimes: tuple[str, ...] = ("low", "normal", "high"),
    minimum_measured_latency_archives: int = 1,
    minimum_execution_samples: int = 10,
    low_max_bps: Decimal = Decimal("0.5"),
    high_min_bps: Decimal = Decimal("2"),
) -> ReplayReadiness:
    rows = list(calibrations)
    if minimum_archives < 1 or minimum_span_days < 0:
        raise ValueError("readiness minimums are invalid")
    reasons: list[str] = []
    unique_hashes = {row.archive_sha256 for row in rows}
    if len(unique_hashes) != len(rows):
        reasons.append("duplicate archive hashes")
    if len(rows) < minimum_archives:
        reasons.append(f"archives {len(rows)} < {minimum_archives}")
    ineligible = sum(not row.eligible for row in rows)
    if ineligible:
        reasons.append(f"ineligible calibrations {ineligible}")
    if rows:
        first = min(row.first_ts_ms for row in rows)
        last = max(row.last_ts_ms for row in rows)
        span_days = Decimal(last - first) / Decimal("86400000")
    else:
        span_days = Decimal("0")
    if span_days < minimum_span_days:
        reasons.append(
            f"archive span {format(span_days, '.3f')}d < {minimum_span_days}d"
        )
    regimes = tuple(sorted({
        volatility_regime(
            row.volatility_bps_p95,
            low_max_bps=low_max_bps,
            high_min_bps=high_min_bps,
        )
        for row in rows
    }))
    missing = sorted(set(required_regimes) - set(regimes))
    if missing:
        reasons.append("missing volatility regimes: " + ",".join(missing))
    measured = sum(
        row.latency_source == "intent_to_execution_report_receive"
        for row in rows
    )
    if measured < minimum_measured_latency_archives:
        reasons.append(
            f"measured latency archives {measured} < "
            f"{minimum_measured_latency_archives}"
        )
    execution_samples = sum(row.execution_sample_count for row in rows)
    if execution_samples < minimum_execution_samples:
        reasons.append(
            f"execution samples {execution_samples} < {minimum_execution_samples}"
        )
    return ReplayReadiness(
        ready=not reasons,
        reasons=tuple(reasons),
        archive_count=len(rows),
        span_days=span_days,
        regimes=regimes,
        measured_latency_archives=measured,
        execution_sample_count=execution_samples,
        book_event_count=sum(row.book_event_count for row in rows),
        trade_count=sum(row.trade_count for row in rows),
    )
