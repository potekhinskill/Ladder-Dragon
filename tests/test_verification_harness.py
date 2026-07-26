# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify fail-closed profiles and non-secret harness artifacts.
"""Regression tests for the unified verification harness."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess

from bin import verification_harness
from deploy import scan_tracked_secrets
from ladder_dragon.verification.dashboard_assets import (
    DASHBOARD_ASSETS,
    dashboard_asset_failures,
)
from ladder_dragon.verification.models import (
    CheckResult,
    CheckSpec,
    HarnessContext,
    HarnessOptions,
    Status,
)
from ladder_dragon.verification.checks.raspberry import raspberry_checks
from ladder_dragon.verification.checks.release_continuity import (
    check_release_continuity,
)
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
        "release_continuity",
        "tracked_secret_scan",
        "replay_regression",
        "walk_forward_approval",
        "recovery_regression",
        "migration_deployment",
    } <= release_names
    pi_names = {
        check.name for check in checks_for_profile(_context(tmp_path, "pi"))
    }
    assert "pi_dashboard_assets" in pi_names


def test_dashboard_asset_audit_fails_closed_on_missing_or_changed_asset(
    tmp_path,
):
    web_root = tmp_path / "web"
    for source_name, published_name in DASHBOARD_ASSETS:
        destination = web_root / published_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(source_name), destination)

    assert dashboard_asset_failures(Path.cwd(), web_root) == ()

    (web_root / "dashboard.css").unlink()
    assert dashboard_asset_failures(Path.cwd(), web_root) == (
        "published_missing:dashboard.css",
    )

    shutil.copy2("FRONT/dashboard.css", web_root / "dashboard.css")
    (web_root / "dashboard.js").write_text(
        "console.error('damaged');\n",
        encoding="utf-8",
    )
    assert dashboard_asset_failures(Path.cwd(), web_root) == (
        "content_mismatch:dashboard.js",
    )


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
        github_sha=expected,
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
    assert passed.metrics["github_sha_matched"] is True

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

    missing_github = replace(options, github_sha=None)
    missing_context = replace(context, options=missing_github)
    missing_spec = next(
        row
        for row in raspberry_checks(missing_context)
        if row.name == "pi_deployed_sha"
    )
    assert (
        HarnessRunner(missing_context)._run_spec(missing_spec).status
        is Status.BLOCKED
    )
    wrong_github = replace(options, github_sha="b" * 40)
    wrong_context = replace(context, options=wrong_github)
    wrong_spec = next(
        row
        for row in raspberry_checks(wrong_context)
        if row.name == "pi_deployed_sha"
    )
    assert (
        HarnessRunner(wrong_context)._run_spec(wrong_spec).status
        is Status.BLOCKED
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_release_surfaces(root: Path, version: str) -> None:
    (root / "product_version.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"Current product version: **{version}**.\n",
        encoding="utf-8",
    )
    changelog = f"## [{version}] — 2026-07-26\n"
    if version != "1.0.0":
        changelog += "\n## [1.0.0] — 2026-07-25\n"
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")


def _release_repository(
    tmp_path: Path,
    *,
    candidate_version: str = "1.0.1",
    trailing_commit: bool = False,
) -> tuple[HarnessContext, str]:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _git(root, "init")
    _git(root, "config", "user.name", "Release Test")
    _git(root, "config", "user.email", "release@example.invalid")
    _write_release_surfaces(root, "1.0.0")
    _git(root, "add", "product_version.py", "README.md", "CHANGELOG.md")
    _git(root, "commit", "-m", "release baseline")
    baseline = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "-a", "v1.0.0", "-m", "release 1.0.0")
    (root / ".release-lineage.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "baseline_version": "1.0.0",
                "baseline_tag": "v1.0.0",
                "baseline_commit": baseline,
                "policy": "strict_linear_releases_after_baseline",
            }
        ),
        encoding="utf-8",
    )
    _write_release_surfaces(root, candidate_version)
    _git(root, "add", ".")
    _git(root, "commit", "-m", f"release {candidate_version}")
    candidate = _git(root, "rev-parse", "HEAD")
    if trailing_commit:
        (root / "extra.txt").write_text("late change\n", encoding="utf-8")
        _git(root, "add", "extra.txt")
        _git(root, "commit", "-m", "late unversioned change")
    return _context(root), candidate


def test_release_continuity_emits_included_commit_manifest(tmp_path):
    context, candidate = _release_repository(tmp_path)

    result = check_release_continuity(context)

    assert result.status is Status.PASS
    assert result.metrics["previous_version"] == "1.0.0"
    assert result.metrics["current_version"] == "1.0.1"
    assert result.metrics["candidate"] is True
    assert result.metrics["included_commits"] == [candidate]


def test_release_continuity_blocks_skips_and_late_unversioned_commits(
    tmp_path,
):
    skipped, _ = _release_repository(
        tmp_path / "skipped",
        candidate_version="1.0.2",
    )
    late, _ = _release_repository(
        tmp_path / "late",
        trailing_commit=True,
    )

    skipped_result = check_release_continuity(skipped)
    late_result = check_release_continuity(late)

    assert skipped_result.status is Status.BLOCKED
    assert "directly follow" in skipped_result.summary
    assert late_result.status is Status.BLOCKED
    assert "branch tip" in late_result.summary


def test_release_continuity_accepts_ci_merge_with_candidate_tip(tmp_path):
    context, candidate = _release_repository(tmp_path)
    lineage = json.loads(
        (context.root / ".release-lineage.json").read_text(encoding="utf-8")
    )
    _git(context.root, "branch", "candidate", candidate)
    _git(
        context.root,
        "switch",
        "-c",
        "integration",
        lineage["baseline_commit"],
    )
    (context.root / "ci.txt").write_text("integration\n", encoding="utf-8")
    _git(context.root, "add", "ci.txt")
    _git(context.root, "commit", "-m", "integration branch")
    _git(
        context.root,
        "merge",
        "--no-ff",
        "candidate",
        "-m",
        "synthetic pull request merge",
    )

    result = check_release_continuity(context)

    assert result.status is Status.PASS
    assert result.metrics["current_version"] == "1.0.1"


def test_release_lineage_baseline_matches_versioned_schema():
    root = Path(__file__).resolve().parents[1]
    baseline = json.loads(
        (root / ".release-lineage.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "schemas/release-lineage-v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert set(baseline) == set(schema["required"])
    assert baseline["schema_version"] == 1
    assert baseline["baseline_tag"] == (
        "v" + baseline["baseline_version"]
    )
    assert len(baseline["baseline_commit"]) == 40
    assert baseline["policy"] == (
        "strict_linear_releases_after_baseline"
    )


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
