from __future__ import annotations

import json

from ladder_dragon.supervision.volatility_guard import (
    evaluate_volatility_guard,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


def policy() -> dict[str, object]:
    return {
        "schema_version": 8,
        "candidate_rule_version": 8,
        "symbol": "SOLUSDT",
        "volatility_activation_policy": (
            "confirmed_post_cutoff_rolling_depth_bucket_v2"
        ),
        "volatility_policy_sha256": "a" * 64,
        "allowed_volatility_buckets": ["low", "normal"],
        "blocked_volatility_buckets": ["high"],
        "volatility_low_max_bps": "0.5",
        "volatility_high_min_bps": "2",
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


def rolling(now_ms: int, volatility: str) -> dict[str, object]:
    body = {
        "schema_version": 1,
        "mode": "PUBLIC_READ_ONLY",
        "apply_allowed": False,
        "contains_secrets": False,
        "symbol": "SOLUSDT",
        "session_id": "session",
        "source": "binance-public-websocket",
        "sequence_verified": True,
        "window_started_at_ms": now_ms - 6 * 60_000,
        "window_ended_at_ms": now_ms - 1_000,
        "updated_at_ms": now_ms - 1_000,
        "book_update_count": 101,
        "last_update_id": 10,
        "volatility_bps_p95": volatility,
    }
    return {**body, "telemetry_sha256": fingerprint(body)}


def test_guard_allows_only_fresh_confirmed_bucket(tmp_path):
    now_ms = 10_000_000
    path = tmp_path / "calibration_inventory.json"
    rolling_path = tmp_path / ".rolling-volatility-SOLUSDT.json"
    path.write_text(json.dumps(inventory(now_ms, "normal")), encoding="utf-8")
    rolling_path.write_text(json.dumps(rolling(now_ms, "1")), encoding="utf-8")

    allowed = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=path,
        rolling_path=rolling_path,
    )
    blocked_payload = inventory(now_ms, "high")
    path.write_text(json.dumps(blocked_payload), encoding="utf-8")
    rolling_path.write_text(json.dumps(rolling(now_ms, "3")), encoding="utf-8")
    blocked = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=path,
        rolling_path=rolling_path,
    )

    assert allowed["allowed"] is True
    assert allowed["bucket"] == "normal"
    assert blocked["allowed"] is False
    assert blocked["reason"] == "UNCONFIRMED_VOLATILITY_BUCKET"


def test_guard_uses_frozen_champion_scope_when_inventory_is_stale(tmp_path):
    now_ms = 100_000_000
    path = tmp_path / "calibration_inventory.json"
    rolling_path = tmp_path / ".rolling-volatility-SOLUSDT.json"
    payload = inventory(now_ms, "low")
    payload["updated_at_ms"] = now_ms - 6 * 60_000
    path.write_text(json.dumps(payload), encoding="utf-8")
    rolling_path.write_text(json.dumps(rolling(now_ms, "0.2")), encoding="utf-8")

    report = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=path,
        rolling_path=rolling_path,
    )

    assert report["allowed"] is True
    assert report["reason"] == "CONFIRMED_VOLATILITY_BUCKET"


def test_guard_fails_closed_on_tampered_or_stale_rolling_telemetry(tmp_path):
    now_ms = 100_000_000
    inventory_path = tmp_path / "calibration_inventory.json"
    rolling_path = tmp_path / ".rolling-volatility-SOLUSDT.json"
    inventory_path.write_text(
        json.dumps(inventory(now_ms, "low")), encoding="utf-8"
    )
    payload = rolling(now_ms, "0.2")
    payload["volatility_bps_p95"] = "0.1"
    rolling_path.write_text(json.dumps(payload), encoding="utf-8")

    tampered = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=inventory_path,
        rolling_path=rolling_path,
    )
    stale_payload = rolling(now_ms - 11 * 60_000, "0.2")
    rolling_path.write_text(json.dumps(stale_payload), encoding="utf-8")
    stale = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=inventory_path,
        rolling_path=rolling_path,
    )

    assert tampered["allowed"] is False
    assert stale["allowed"] is False


def test_guard_rejects_future_rolling_telemetry(tmp_path):
    now_ms = 100_000_000
    inventory_path = tmp_path / "calibration_inventory.json"
    rolling_path = tmp_path / ".rolling-volatility-SOLUSDT.json"
    inventory_path.write_text(
        json.dumps(inventory(now_ms, "low")), encoding="utf-8"
    )
    rolling_path.write_text(
        json.dumps(rolling(now_ms + 10_000, "0.2")), encoding="utf-8"
    )

    report = evaluate_volatility_guard(
        policy(), now_ms=now_ms, inventory_path=inventory_path,
        rolling_path=rolling_path,
    )

    assert report["allowed"] is False
