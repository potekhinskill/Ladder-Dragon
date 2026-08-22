from __future__ import annotations

from decimal import Decimal
import json

import pytest

from ladder_dragon.verification.live import validation_batch


COMMIT = "a" * 40


def _manifest(tmp_path, *, attempts: int = 2, turnover: str = "24"):
    return validation_batch.create_batch_manifest(
        tmp_path / "batch.json",
        symbol="SOLUSDT",
        maximum_attempts=attempts,
        maximum_turnover_usdt=Decimal(turnover),
        duration_hours=24,
        created_at_ms=1_000,
        source_commit=COMMIT,
    )


def test_batch_reserves_before_mutation_and_stops_at_attempt_limit(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)

    first = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="LIMIT_MAKER",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("12"),
        now_ms=2_000,
    )
    second = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="STOP_LOSS_LIMIT",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("12"),
        now_ms=3_000,
    )

    assert first["status"] == "RESERVED_BEFORE_MUTATION"
    assert first["manifest_sha256"] == manifest["manifest_sha256"]
    assert second["attempt_id"] != first["attempt_id"]
    with pytest.raises(RuntimeError, match="attempt limit reached"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="LIMIT_MAKER",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("1"),
            now_ms=4_000,
        )


def test_batch_fails_closed_on_turnover_expiry_and_manifest_damage(
    tmp_path, monkeypatch
):
    _manifest(tmp_path, attempts=3, turnover="12")
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="LIMIT_MAKER",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("12"),
        now_ms=2_000,
    )
    with pytest.raises(RuntimeError, match="turnover limit reached"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="STOP_LOSS_LIMIT",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("1"),
            now_ms=3_000,
        )
    with pytest.raises(RuntimeError, match="expired"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="STOP_LOSS_LIMIT",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("1"),
            now_ms=24 * 60 * 60_000 + 2_000,
        )

    payload = json.loads((tmp_path / "batch.json").read_text())
    payload["maximum_attempts"] = 10
    (tmp_path / "batch.json").write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="fingerprint differs"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="LIMIT_MAKER",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("1"),
            now_ms=4_000,
        )


def test_batch_artifacts_do_not_contain_credentials(tmp_path):
    payload = _manifest(tmp_path)

    encoded = json.dumps(payload)
    assert "API_KEY" not in encoded
    assert "API_SECRET" not in encoded


def test_batch_enforces_drill_quotas_cooldown_and_ledger_chain(
    tmp_path, monkeypatch
):
    validation_batch.create_batch_manifest(
        tmp_path / "batch.json",
        symbol="SOLUSDT",
        maximum_attempts=2,
        maximum_turnover_usdt=Decimal("24"),
        duration_hours=24,
        created_at_ms=1_000,
        source_commit=COMMIT,
        limit_maker_attempts=1,
        stop_limit_attempts=1,
        minimum_cooldown_sec=60,
    )
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    first = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="LIMIT_MAKER",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("6"),
        now_ms=2_000,
    )
    assert first["previous_entry_sha256"] == "0" * 64
    with pytest.raises(RuntimeError, match="quota"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="LIMIT_MAKER",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=70_000,
        )
    with pytest.raises(RuntimeError, match="cooldown"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="STOP_LOSS_LIMIT",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=3_000,
        )
    second = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="STOP_LOSS_LIMIT",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("6"),
        now_ms=70_000,
    )
    assert second["previous_entry_sha256"] == first["entry_sha256"]

    ledger = tmp_path / "batch.json.attempts.ndjson"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    rows[0]["turnover_usdt"] = "1"
    ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(RuntimeError, match="ledger is invalid"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="STOP_LOSS_LIMIT",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("1"),
            now_ms=140_000,
        )
