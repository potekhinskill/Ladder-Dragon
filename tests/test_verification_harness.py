# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify fail-closed profiles and non-secret harness artifacts.
"""Regression tests for the unified verification harness."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

from bin import verification_harness
from deploy import scan_tracked_secrets
from ladder_dragon.verification.models import (
    CheckResult,
    CheckSpec,
    HarnessContext,
    HarnessOptions,
    Status,
)
from ladder_dragon.verification.checks.raspberry import raspberry_checks
from ladder_dragon.verification.profiles import (
    KNOWN_PROFILES,
    checks_for_profile,
)
from ladder_dragon.verification.report import build_report, write_report
from ladder_dragon.verification.runner import HarnessRunner


def _context(tmp_path: Path, profile: str = "local") -> HarnessContext:
    return HarnessContext(
        root=tmp_path,
        python="python",
        options=HarnessOptions(
            profile=profile,
            output=tmp_path / "report.json",
            order_journal=tmp_path / "orders.sqlite3",
            prediction_db=tmp_path / "prediction.sqlite3",
            ai_decisions_db=tmp_path / "ai.sqlite3",
            runtime_status=tmp_path / "runtime.json",
            user_stream_status=tmp_path / "stream.json",
            risk_status=tmp_path / "risk.json",
        ),
    )


def test_profile_registry_contains_the_documented_interfaces(tmp_path):
    assert KNOWN_PROFILES == (
        "local",
        "release",
        "testnet",
        "pi",
        "mainnet-canary",
    )
    release_names = {
        check.name for check in checks_for_profile(_context(tmp_path, "release"))
    }
    assert {
        "source_compile",
        "pytest",
        "numeric_boundary_audit",
        "tracked_secret_scan",
        "replay_regression",
        "walk_forward_approval",
        "recovery_regression",
        "migration_deployment",
    } <= release_names


def test_unknown_profile_and_missing_check_fail_closed(tmp_path):
    context = _context(tmp_path, "unexpected")
    result = HarnessRunner(context).run()
    assert len(result) == 1
    assert result[0].status is Status.BLOCKED
    assert "unknown verification profile" in result[0].summary

    missing = HarnessRunner(context)._run_spec(CheckSpec(name="missing"))
    assert missing.status is Status.BLOCKED
    assert missing.exit_code == 2


def test_testnet_and_mainnet_mutations_require_separate_confirmations(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("BOT_TESTNET_BUY_OCO_CONFIRMED", raising=False)
    testnet = checks_for_profile(_context(tmp_path, "testnet"))
    blocked = {row.name: row.blocked_reason for row in testnet}
    assert blocked["testnet_authenticated"]
    assert blocked["testnet_buy_oco_restart"]

    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    monkeypatch.setenv("BOT_MAINNET_CANARY_CONFIRMED", "YES")
    monkeypatch.delenv(
        "BOT_MAINNET_CANARY_CLEANUP_CONFIRMED", raising=False
    )
    mainnet = checks_for_profile(_context(tmp_path, "mainnet-canary"))
    mainnet_canary = next(
        row for row in mainnet if row.name == "mainnet_canary"
    )
    assert mainnet_canary.blocked_reason


def test_pi_accepts_only_sha_linked_to_passed_release_artifact(
    tmp_path, monkeypatch
):
    expected = "a" * 40
    release = tmp_path / "release.json"
    release.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "release",
                "status": "PASS",
                "commit_sha": expected,
            }
        ),
        encoding="utf-8",
    )
    options = HarnessOptions(
        profile="pi",
        output=tmp_path / "pi.json",
        expected_sha=expected,
        release_report=release,
        order_journal=tmp_path / "orders.sqlite3",
        prediction_db=tmp_path / "prediction.sqlite3",
        ai_decisions_db=tmp_path / "ai.sqlite3",
    )
    context = HarnessContext(root=tmp_path, python="python", options=options)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout=expected + "\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    spec = next(
        row for row in raspberry_checks(context) if row.name == "pi_deployed_sha"
    )
    passed = HarnessRunner(context)._run_spec(spec)
    assert passed.status is Status.PASS
    assert passed.metrics["release_artifact_verified"] is True

    release.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "release",
                "status": "BLOCKED",
                "commit_sha": expected,
            }
        ),
        encoding="utf-8",
    )
    blocked = HarnessRunner(context)._run_spec(spec)
    assert blocked.status is Status.BLOCKED


def test_child_output_cannot_leak_secrets_into_result(tmp_path, monkeypatch):
    secret = "signature=super-secret-value"

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["fake"],
            returncode=1,
            stdout=f"api_key={secret}",
            stderr=f"https://api.binance.com/api/v3/order?{secret}",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = HarnessRunner(_context(tmp_path))._run_spec(
        CheckSpec(name="noisy_failure", argv=("fake",))
    )
    rendered = json.dumps(result.as_dict())
    assert result.status is Status.FAILED
    assert "super-secret-value" not in rendered
    assert "signature=" not in rendered
    assert "api_key" not in rendered


def test_secret_assignment_scan_ignores_lowercase_code_identifiers():
    source = (
        "private_key = serialization.load_pem_private_key(payload)\n"
        "BINANCE_API_SECRET=AbCdEfGhIjKlMnOpQrStUvWxYz012345\n"
    )
    matches = scan_tracked_secrets.SECRET_ASSIGNMENT.findall(source)
    assert matches == [
        ("BINANCE_API_SECRET", "AbCdEfGhIjKlMnOpQrStUvWxYz012345")
    ]


def test_pytest_metrics_are_allowlisted_without_storing_output(
    tmp_path, monkeypatch
):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["pytest"],
            returncode=0,
            stdout="520 passed, 2 skipped in 1.0s",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = HarnessRunner(_context(tmp_path))._run_spec(
        CheckSpec(name="pytest", argv=("python", "-m", "pytest"))
    )
    assert result.metrics == {"passed": 520, "skipped": 2}
    assert "520 passed" not in result.summary


def test_report_has_versioned_schema_fields_and_owner_only_mode(tmp_path):
    context = _context(tmp_path)
    checks = (
        CheckResult(
            name="unit",
            status=Status.PASS,
            required=True,
            duration_ms=1,
            summary="check passed",
            exit_code=0,
            metrics={"passed": 5},
        ),
    )
    report = build_report(context, checks, "a" * 40)
    output = tmp_path / "report.json"
    write_report(output, report)
    payload = json.loads(output.read_text(encoding="utf-8"))
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "verification-report-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert set(schema["required"]) == set(payload)
    assert payload["schema_version"] == 1
    assert payload["status"] == "PASS"
    assert payload["tests"]["passed"] == 5
    assert payload["replay"]["accuracy"] is None
    assert payload["latency_ms"] is None
    assert payload["unresolved_fills"] is None
    assert stat_mode(output) == 0o600


def test_report_collects_hashed_replay_and_latency_evidence(tmp_path):
    replay = tmp_path / "validation.json"
    replay.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "ready": True,
                "reasons": [],
                "archive_sha256": "b" * 64,
                "covered_orders": 12,
                "excluded_orders": 1,
                "actual_filled_orders": 6,
                "replay_filled_orders": 6,
                "fill_classification_accuracy": "0.9167",
                "fill_ratio_mae": "0.10",
                "price_error_bps_mae": "2.5",
                "latency_error_ms_mae": "40",
                "fee_error_quote_mae": "0.001",
                "slippage_error_bps_mae": "1.5",
                "queue_model": "L2_PRICE_LEVEL_FIFO_PROXY",
                "exact_l3": False,
            }
        ),
        encoding="utf-8",
    )
    latency = tmp_path / "latency.ndjson"
    latency.write_text(
        "\n".join(
            json.dumps(
                {
                    "schema_version": 3,
                    "execution_type": "NEW",
                    "order_status": "NEW",
                    "intent_to_receive_ms": value,
                }
            )
            for value in (100, 200, 300, 400, 500)
        )
        + "\n",
        encoding="utf-8",
    )
    base = _context(tmp_path)
    options = replace(
        base.options,
        replay_validation=replay,
        latency_log=latency,
    )
    context = HarnessContext(
        root=base.root, python=base.python, options=options
    )
    report = build_report(
        context,
        (
            CheckResult(
                name="evidence",
                status=Status.PASS,
                required=True,
                duration_ms=1,
                summary="check passed",
            ),
        ),
        "c" * 40,
    ).as_dict()
    assert report["replay"]["accuracy"] == "0.9167"
    assert report["replay"]["errors"]["latency_ms_mae"] == "40"
    assert report["latency_ms"] == {
        "samples": 5,
        "p50": 300,
        "p95": 500,
    }
    assert report["input_hashes"][str(replay)]
    assert report["input_hashes"][str(latency)]


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def test_cli_unknown_profile_writes_blocked_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(verification_harness, "PROJECT_ROOT", tmp_path)
    output = tmp_path / "blocked.json"
    result = verification_harness.main(
        [
            "--profile",
            "not-a-profile",
            "--output",
            str(output),
            "--order-journal",
            str(tmp_path / "missing-orders.sqlite3"),
            "--prediction-db",
            str(tmp_path / "missing-prediction.sqlite3"),
            "--ai-decisions-db",
            str(tmp_path / "missing-ai.sqlite3"),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result == 2
    assert payload["status"] == "BLOCKED"
    assert payload["block_reasons"]
