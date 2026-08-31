# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce immutable CHAMPION volatility buckets from public depth data.
"""Fail-closed runtime guard for bucket-scoped volatility confirmation."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Mapping
from decimal import Decimal, InvalidOperation

from ladder_dragon.strategy.depth_segments import bounded_json
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.rolling_volatility import (
    CURRENT_DEPTH_SESSION_FILENAME,
    ROLLING_VOLATILITY_FILENAME,
    ROLLING_WINDOW_MS,
)
from ladder_dragon.strategy.volatility_policy import (
    VOLATILITY_EVENT_POPULATION,
    VOLATILITY_METRIC,
    VOLATILITY_PUBLISH_INTERVAL_MS,
)
from ladder_dragon.strategy.prediction.champion_registry import (
    champion_allows_volatility,
)


MAXIMUM_ROLLING_TELEMETRY_AGE_MS = 10 * 60_000
MAXIMUM_FUTURE_SKEW_MS = 5_000


def evaluate_volatility_guard(
    policy: Mapping[str, object],
    *,
    now_ms: int | None = None,
    inventory_path: Path = Path(
        "/var/lib/ladder-dragon/depth-archives/calibration_inventory.json"
    ),
    rolling_path: Path | None = None,
) -> dict[str, object]:
    """Allow BUY only from fresh policy-bound rolling public telemetry."""
    observed_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    blocked = {
        "allowed": False,
        "bucket": None,
        "reason": "VOLATILITY_EVIDENCE_UNAVAILABLE",
    }
    try:
        rolling = bounded_json(
            rolling_path
            or inventory_path.parent / ROLLING_VOLATILITY_FILENAME
        )
        current_session = bounded_json(
            (rolling_path.parent if rolling_path is not None else inventory_path.parent)
            / CURRENT_DEPTH_SESSION_FILENAME
        )
        current_session_body = {
            key: value for key, value in current_session.items()
            if key != "session_sha256"
        }
        rolling_body = {
            key: value for key, value in rolling.items()
            if key != "telemetry_sha256"
        }
        rolling_updated_ms = int(rolling.get("updated_at_ms", 0))
        window_started_ms = int(rolling.get("window_started_at_ms", 0))
        window_ended_ms = int(rolling.get("window_ended_at_ms", 0))
        try:
            volatility = Decimal(str(rolling["volatility_bps_p95"]))
            low = Decimal(str(policy["volatility_low_max_bps"]))
            high = Decimal(str(policy["volatility_high_min_bps"]))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return blocked
        bucket = (
            "low" if volatility <= low
            else "high" if volatility >= high
            else "normal"
        )
        if (
            rolling.get("schema_version") != 2
            or rolling.get("mode") != "PUBLIC_READ_ONLY"
            or rolling.get("apply_allowed") is not False
            or rolling.get("contains_secrets") is not False
            or rolling.get("symbol") != policy.get("symbol")
            or rolling.get("sequence_verified") is not True
            or rolling.get("volatility_metric") != VOLATILITY_METRIC
            or rolling.get("volatility_event_population")
            != VOLATILITY_EVENT_POPULATION
            or rolling.get("measurement_window_ms") != ROLLING_WINDOW_MS
            or rolling.get("publish_interval_ms")
            != VOLATILITY_PUBLISH_INTERVAL_MS
            or policy.get("volatility_measurement_window_ms")
            != ROLLING_WINDOW_MS
            or policy.get("volatility_publish_interval_ms")
            != VOLATILITY_PUBLISH_INTERVAL_MS
            or policy.get("volatility_metric") != VOLATILITY_METRIC
            or policy.get("volatility_event_population")
            != VOLATILITY_EVENT_POPULATION
            or current_session.get("schema_version") != 1
            or current_session.get("mode") != "PUBLIC_READ_ONLY"
            or current_session.get("apply_allowed") is not False
            or current_session.get("contains_secrets") is not False
            or current_session.get("symbol") != policy.get("symbol")
            or current_session.get("status") != "READY"
            or current_session.get("sequence_verified") is not True
            or current_session.get("session_id") != rolling.get("session_id")
            or current_session.get("updated_at_ms") != rolling_updated_ms
            or current_session.get("last_update_id")
            != rolling.get("last_update_id")
            or current_session.get("session_sha256")
            != fingerprint(current_session_body)
            or rolling.get("telemetry_sha256") != fingerprint(rolling_body)
            or not volatility.is_finite()
            or volatility < 0
            or not Decimal("0") <= low < high
            or rolling_updated_ms <= 0
            or window_started_ms <= 0
            or window_ended_ms != rolling_updated_ms
            or type(rolling.get("book_update_count")) is not int
            or int(rolling["book_update_count"]) < 100
            or type(rolling.get("last_update_id")) is not int
            or int(rolling["last_update_id"]) <= 0
            or rolling_updated_ms > observed_at_ms + MAXIMUM_FUTURE_SKEW_MS
            or window_started_ms > rolling_updated_ms
            or rolling_updated_ms - window_started_ms != ROLLING_WINDOW_MS
            or observed_at_ms - rolling_updated_ms
            > MAXIMUM_ROLLING_TELEMETRY_AGE_MS
        ):
            return blocked
        allowed = champion_allows_volatility(policy, bucket)
        return {
            "allowed": allowed,
            "bucket": bucket,
            "reason": (
                "CONFIRMED_VOLATILITY_BUCKET"
                if allowed else "UNCONFIRMED_VOLATILITY_BUCKET"
            ),
            "rolling_updated_at_ms": rolling_updated_ms,
            "volatility_bps_p95": format(volatility, "f"),
        }
    except (OSError, TypeError, ValueError, ArithmeticError):
        return blocked


def champion_volatility_context(
    champion: Mapping[str, object] | None, *, execution_allowed: bool
) -> tuple[Mapping[str, object] | None, dict[str, object]]:
    """Load one CHAMPION policy and its protective volatility decision."""
    policy = (
        champion.get("execution_policy")
        if isinstance(champion, Mapping) else None
    )
    if execution_allowed and not isinstance(policy, Mapping):
        raise RuntimeError("active CHAMPION execution policy is unavailable")
    report = (
        evaluate_volatility_guard(policy)
        if isinstance(policy, Mapping)
        and policy.get("candidate_rule_version") == 8
        else {"allowed": True, "bucket": None, "reason": "NO_CHAMPION"}
    )
    return policy, report


__all__ = ["champion_volatility_context", "evaluate_volatility_guard"]
