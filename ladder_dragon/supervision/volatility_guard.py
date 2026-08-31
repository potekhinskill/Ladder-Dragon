# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce immutable CHAMPION volatility buckets from public depth data.
"""Fail-closed runtime guard for bucket-scoped volatility confirmation."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Mapping

from ladder_dragon.strategy.depth_segments import bounded_json
from ladder_dragon.strategy.prediction.champion_registry import (
    champion_allows_volatility,
)


MAXIMUM_INVENTORY_AGE_MS = 5 * 60_000
MAXIMUM_COMPLETED_SEGMENT_AGE_MS = 30 * 60_000
MAXIMUM_FUTURE_SKEW_MS = 5_000


def evaluate_volatility_guard(
    policy: Mapping[str, object],
    *,
    now_ms: int | None = None,
    inventory_path: Path = Path(
        "/var/lib/ladder-dragon/depth-archives/calibration_inventory.json"
    ),
) -> dict[str, object]:
    """Allow BUY only from a fresh, policy-bound completed depth segment."""
    observed_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    blocked = {
        "allowed": False,
        "bucket": None,
        "reason": "VOLATILITY_EVIDENCE_UNAVAILABLE",
    }
    try:
        payload = bounded_json(inventory_path)
        status = payload.get("frozen_volatility_policy")
        updated_at_ms = int(payload.get("updated_at_ms", 0))
        if not isinstance(status, Mapping):
            return blocked
        latest_ms = int(status.get("latest_bucket_last_ts_ms", 0))
        bucket = str(status.get("latest_bucket") or "")
        if (
            status.get("status") != "PASS_SCOPED"
            or status.get("policy_sha256")
            != policy.get("volatility_policy_sha256")
            or updated_at_ms <= 0
            or latest_ms <= 0
            or updated_at_ms > observed_at_ms + MAXIMUM_FUTURE_SKEW_MS
            or latest_ms > observed_at_ms + MAXIMUM_FUTURE_SKEW_MS
            or observed_at_ms - updated_at_ms > MAXIMUM_INVENTORY_AGE_MS
            or observed_at_ms - latest_ms > MAXIMUM_COMPLETED_SEGMENT_AGE_MS
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
            "inventory_updated_at_ms": updated_at_ms,
            "segment_last_ts_ms": latest_ms,
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
