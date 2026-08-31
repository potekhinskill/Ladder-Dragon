from __future__ import annotations

import json

from ladder_dragon.supervision.volatility_guard import (
    evaluate_volatility_guard,
)


def policy() -> dict[str, object]:
    return {
        "schema_version": 7,
        "candidate_rule_version": 8,
        "volatility_activation_policy": (
            "confirmed_post_cutoff_depth_bucket_only_v1"
        ),
        "volatility_policy_sha256": "a" * 64,
        "allowed_volatility_buckets": ["low", "normal"],
        "blocked_volatility_buckets": ["high"],
    }


def inventory(now_ms: int, bucket: str) -> dict[str, object]:
    return {
        "updated_at_ms": now_ms - 1_000,
        "frozen_volatility_policy": {
            "status": "PASS_SCOPED",
            "policy_sha256": "a" * 64,
            "confirmed_buckets": ["low", "normal"],
            "blocked_buckets": ["high"],
            "latest_bucket": bucket,
            "latest_bucket_last_ts_ms": now_ms - 60_000,
        },
    }


def test_guard_allows_only_fresh_confirmed_bucket(tmp_path):
    now_ms = 10_000_000
    path = tmp_path / "calibration_inventory.json"
    path.write_text(json.dumps(inventory(now_ms, "normal")), encoding="utf-8")

    allowed = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=path
    )
    blocked_payload = inventory(now_ms, "high")
    path.write_text(json.dumps(blocked_payload), encoding="utf-8")
    blocked = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=path
    )

    assert allowed["allowed"] is True
    assert allowed["bucket"] == "normal"
    assert blocked["allowed"] is False
    assert blocked["reason"] == "UNCONFIRMED_VOLATILITY_BUCKET"


def test_guard_fails_closed_on_stale_inventory(tmp_path):
    now_ms = 100_000_000
    path = tmp_path / "calibration_inventory.json"
    payload = inventory(now_ms, "low")
    payload["updated_at_ms"] = now_ms - 6 * 60_000
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=path
    )

    assert report == {
        "allowed": False,
        "bucket": None,
        "reason": "VOLATILITY_EVIDENCE_UNAVAILABLE",
    }
