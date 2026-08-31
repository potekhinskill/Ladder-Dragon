from __future__ import annotations

from decimal import Decimal
import json
from types import SimpleNamespace

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
    validation_batch.complete_validation_attempt(
        tmp_path / "batch.json",
        attempt_id=first["attempt_id"],
        status="SUCCEEDED",
        archive_path="first.jsonl",
        archive_sha256="1" * 64,
        order_refs=("first-order",),
        completed_at_ms=2_500,
    )
    second = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="STOP_LOSS_LIMIT",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("12"),
        now_ms=3_000,
    )
    validation_batch.complete_validation_attempt(
        tmp_path / "batch.json",
        attempt_id=second["attempt_id"],
        status="SUCCEEDED",
        archive_path="second.jsonl",
        archive_sha256="2" * 64,
        order_refs=("second-order",),
        completed_at_ms=3_500,
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
    first = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="LIMIT_MAKER",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("12"),
        now_ms=2_000,
    )
    validation_batch.complete_validation_attempt(
        tmp_path / "batch.json",
        attempt_id=first["attempt_id"],
        status="SUCCEEDED",
        archive_sha256="1" * 64,
        order_refs=("first-order",),
        completed_at_ms=2_500,
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
    with pytest.raises(RuntimeError, match="unfinished attempt"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="LIMIT_MAKER",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=70_000,
        )
    validation_batch.complete_validation_attempt(
        tmp_path / "batch.json",
        attempt_id=first["attempt_id"],
        status="SUCCEEDED",
        archive_sha256="1" * 64,
        order_refs=("first-order",),
        completed_at_ms=2_500,
    )
    with pytest.raises(RuntimeError, match="fixed sequence"):
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
    assert second["previous_entry_sha256"] != first["entry_sha256"]

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


def test_uncertain_attempt_permanently_closes_batch(tmp_path, monkeypatch):
    _manifest(tmp_path)
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    reservation = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="LIMIT_MAKER",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("6"),
        now_ms=2_000,
    )
    validation_batch.complete_validation_attempt(
        tmp_path / "batch.json",
        attempt_id=reservation["attempt_id"],
        status="FAILED_UNCERTAIN",
        archive_sha256="1" * 64,
        completed_at_ms=3_000,
    )
    with pytest.raises(RuntimeError, match="permanently closed"):
        validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill="STOP_LOSS_LIMIT",
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=4_000,
        )


def test_definite_failure_consumes_attempt_but_allows_fixed_sequence(
    tmp_path, monkeypatch
):
    _manifest(tmp_path)
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    reservation = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="LIMIT_MAKER",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("6"),
        now_ms=2_000,
    )
    validation_batch.complete_validation_attempt(
        tmp_path / "batch.json",
        attempt_id=reservation["attempt_id"],
        status="FAILED_DEFINITE",
        completed_at_ms=3_000,
    )

    second = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="STOP_LOSS_LIMIT",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("6"),
        now_ms=4_000,
    )

    assert second["status"] == "RESERVED_BEFORE_MUTATION"


def test_definite_failure_cannot_enter_successful_batch_evidence(
    tmp_path, monkeypatch
):
    _manifest(tmp_path, attempts=1, turnover="12")
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    reservation = validation_batch.reserve_validation_attempt(
        tmp_path / "batch.json",
        drill="LIMIT_MAKER",
        symbol="SOLUSDT",
        turnover_usdt=Decimal("6"),
        now_ms=2_000,
    )
    validation_batch.complete_validation_attempt(
        tmp_path / "batch.json",
        attempt_id=reservation["attempt_id"],
        status="FAILED_DEFINITE",
        completed_at_ms=3_000,
    )

    with pytest.raises(RuntimeError, match="insufficient covered attempts"):
        validation_batch.validation_batch_evidence(tmp_path / "batch.json")


def test_batch_runner_continues_after_definite_failure(
    tmp_path, monkeypatch
):
    _manifest(tmp_path)
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    monkeypatch.setenv("BOT_MAINNET_VALIDATION_BATCH_RUN_CONFIRMED", "YES")
    calls: list[str] = []

    def run_child(command, **_kwargs):
        drill = (
            "LIMIT_MAKER"
            if "mainnet_limit_maker_validation" in command[2]
            else "STOP_LOSS_LIMIT"
        )
        calls.append(drill)
        reservation = validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill=drill,
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=2_000 + len(calls) * 1_000,
        )
        status = "FAILED_DEFINITE" if len(calls) == 1 else "SUCCEEDED"
        validation_batch.complete_validation_attempt(
            tmp_path / "batch.json",
            attempt_id=reservation["attempt_id"],
            status=status,
            archive_sha256=("2" * 64 if status == "SUCCEEDED" else None),
            order_refs=(("second-order",) if status == "SUCCEEDED" else ()),
            completed_at_ms=2_500 + len(calls) * 1_000,
        )
        return SimpleNamespace(returncode=3 if status == "FAILED_DEFINITE" else 0)

    monkeypatch.setattr(validation_batch.subprocess, "run", run_child)

    result = validation_batch.run_validation_batch(
        tmp_path / "batch.json", notional_usdt=Decimal("6")
    )

    assert result == 3
    assert calls == ["LIMIT_MAKER", "STOP_LOSS_LIMIT"]


def test_complete_batch_freezes_archives_and_order_refs(tmp_path, monkeypatch):
    _manifest(tmp_path)
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    for index, drill in enumerate(("LIMIT_MAKER", "STOP_LOSS_LIMIT"), start=1):
        reservation = validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill=drill,
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=index * 2_000,
        )
        validation_batch.complete_validation_attempt(
            tmp_path / "batch.json",
            attempt_id=reservation["attempt_id"],
            status="SUCCEEDED",
            archive_path=f"archive-{index}.jsonl",
            archive_sha256=str(index) * 64,
            order_refs=(f"order-{index}",),
            completed_at_ms=index * 2_000 + 500,
        )
    evidence = validation_batch.validation_batch_evidence(
        tmp_path / "batch.json"
    )
    assert evidence["status"] == "COHORT_COMPLETE_NOT_REPLAY_READY"
    assert evidence["replay_readiness_proven"] is False
    assert evidence["successful_attempts_by_drill"] == {
        "LIMIT_MAKER": 1,
        "STOP_LOSS_LIMIT": 1,
    }
    assert evidence["attempt_count"] == 2
    assert evidence["successful_attempt_count"] == 2
    assert evidence["definite_failure_count"] == 0
    assert evidence["archive_sha256s"] == ["1" * 64, "2" * 64]
    assert evidence["order_refs"] == ["order-1", "order-2"]


def test_twelve_attempt_cohort_accepts_two_definite_failures(tmp_path, monkeypatch):
    validation_batch.create_batch_manifest(
        tmp_path / "batch.json",
        symbol="SOLUSDT",
        maximum_attempts=12,
        minimum_successful_attempts=10,
        maximum_turnover_usdt=Decimal("72"),
        duration_hours=24,
        created_at_ms=1_000,
        source_commit=COMMIT,
    )
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    for index in range(12):
        drill = "LIMIT_MAKER" if index % 2 == 0 else "STOP_LOSS_LIMIT"
        reservation = validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill=drill,
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=2_000 + index * 1_000,
        )
        succeeded = index < 10
        validation_batch.complete_validation_attempt(
            tmp_path / "batch.json",
            attempt_id=reservation["attempt_id"],
            status="SUCCEEDED" if succeeded else "FAILED_DEFINITE",
            archive_sha256=(format(index + 1, "064x") if succeeded else None),
            order_refs=((f"order-{index}",) if succeeded else ()),
            completed_at_ms=2_500 + index * 1_000,
        )

    evidence = validation_batch.validation_batch_evidence(
        tmp_path / "batch.json"
    )

    assert evidence["attempt_count"] == 12
    assert evidence["successful_attempt_count"] == 10
    assert evidence["definite_failure_count"] == 2
    assert len(evidence["terminal_outcomes"]) == 12
    assert len(evidence["archive_sha256s"]) == 10


def test_complete_cohort_requires_successful_coverage_for_each_drill(
    tmp_path, monkeypatch
):
    validation_batch.create_batch_manifest(
        tmp_path / "batch.json",
        symbol="SOLUSDT",
        maximum_attempts=3,
        minimum_successful_attempts=2,
        maximum_turnover_usdt=Decimal("18"),
        duration_hours=24,
        created_at_ms=1_000,
        source_commit=COMMIT,
        limit_maker_attempts=2,
        stop_limit_attempts=1,
    )
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    outcomes = (
        ("LIMIT_MAKER", "SUCCEEDED"),
        ("STOP_LOSS_LIMIT", "FAILED_DEFINITE"),
        ("LIMIT_MAKER", "SUCCEEDED"),
    )
    for index, (drill, status) in enumerate(outcomes, start=1):
        reservation = validation_batch.reserve_validation_attempt(
            tmp_path / "batch.json",
            drill=drill,
            symbol="SOLUSDT",
            turnover_usdt=Decimal("6"),
            now_ms=2_000 + index * 1_000,
        )
        validation_batch.complete_validation_attempt(
            tmp_path / "batch.json",
            attempt_id=reservation["attempt_id"],
            status=status,
            archive_sha256=(format(index, "064x") if status == "SUCCEEDED" else None),
            order_refs=((f"order-{index}",) if status == "SUCCEEDED" else ()),
            completed_at_ms=2_500 + index * 1_000,
        )

    with pytest.raises(RuntimeError, match="drill coverage is insufficient"):
        validation_batch.validation_batch_evidence(tmp_path / "batch.json")
