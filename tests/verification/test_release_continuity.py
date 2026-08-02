# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify strict release continuity for direct and GitHub PR commits.
"""Release-continuity checks for candidate commit topology."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from ladder_dragon.verification.checks.release_continuity import (
    check_release_continuity,
)
from ladder_dragon.verification.models import (
    HarnessContext,
    HarnessOptions,
    Status,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _context(root: Path) -> HarnessContext:
    return HarnessContext(
        root=root,
        python="python",
        options=HarnessOptions(
            profile="local",
            output=root / "report.json",
            order_journal=root / "orders.sqlite3",
            prediction_db=root / "prediction.sqlite3",
            ai_decisions_db=root / "ai.sqlite3",
            runtime_status=root / "runtime.json",
            user_stream_status=root / "stream.json",
            risk_status=root / "risk.json",
        ),
    )


def _write_release_surfaces(root: Path, version: str) -> None:
    (root / "product_version.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (root / "README.md").write_text(
        f"Current product version: **{version}**.\n", encoding="utf-8"
    )
    changelog = f"## [{version}] — 2026-08-02\n"
    if version != "1.0.0":
        changelog += "\n## [1.0.0] — 2026-08-01\n"
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
        json.dumps({
            "schema_version": 1,
            "baseline_version": "1.0.0",
            "baseline_tag": "v1.0.0",
            "baseline_commit": baseline,
            "policy": "strict_linear_releases_after_baseline",
        }),
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


def _merge_candidate(context: HarnessContext, candidate: str) -> str:
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
    return _git(context.root, "rev-parse", "HEAD")


def _set_pull_request_environment(
    monkeypatch,
    tmp_path: Path,
    *,
    merge_sha: str,
    candidate_sha: str,
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"pull_request": {"head": {"sha": candidate_sha}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/17/merge")
    monkeypatch.setenv("GITHUB_SHA", merge_sha)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))


def test_release_continuity_emits_included_commit_manifest(tmp_path):
    context, candidate = _release_repository(tmp_path)

    result = check_release_continuity(context)

    assert result.status is Status.PASS
    assert result.metrics["previous_version"] == "1.0.0"
    assert result.metrics["current_version"] == "1.0.1"
    assert result.metrics["candidate"] is True
    assert result.metrics["included_commits"] == [candidate]


def test_release_continuity_blocks_skips_and_late_unversioned_commits(tmp_path):
    skipped, _ = _release_repository(
        tmp_path / "skipped", candidate_version="1.0.2"
    )
    late, _ = _release_repository(tmp_path / "late", trailing_commit=True)

    skipped_result = check_release_continuity(skipped)
    late_result = check_release_continuity(late)

    assert skipped_result.status is Status.BLOCKED
    assert "directly follow" in skipped_result.summary
    assert late_result.status is Status.BLOCKED
    assert "branch tip" in late_result.summary


def test_release_continuity_accepts_verified_github_pr_merge(
    tmp_path,
    monkeypatch,
):
    context, candidate = _release_repository(tmp_path)
    merge_sha = _merge_candidate(context, candidate)
    _set_pull_request_environment(
        monkeypatch,
        tmp_path,
        merge_sha=merge_sha,
        candidate_sha=candidate,
    )

    result = check_release_continuity(context)

    assert result.status is Status.PASS
    assert result.metrics["current_version"] == "1.0.1"


def test_release_continuity_blocks_local_merge_without_pr_evidence(tmp_path):
    context, candidate = _release_repository(tmp_path)
    _merge_candidate(context, candidate)

    result = check_release_continuity(context)

    assert result.status is Status.BLOCKED
    assert "branch tip" in result.summary


def test_release_continuity_blocks_pr_event_with_wrong_head(
    tmp_path,
    monkeypatch,
):
    context, candidate = _release_repository(tmp_path)
    merge_sha = _merge_candidate(context, candidate)
    _set_pull_request_environment(
        monkeypatch,
        tmp_path,
        merge_sha=merge_sha,
        candidate_sha="a" * 40,
    )

    result = check_release_continuity(context)

    assert result.status is Status.BLOCKED
    assert "branch tip" in result.summary


def test_release_continuity_blocks_version_change_on_pr_base(
    tmp_path,
    monkeypatch,
):
    context, version_commit = _release_repository(tmp_path)
    lineage = json.loads(
        (context.root / ".release-lineage.json").read_text(encoding="utf-8")
    )
    _git(context.root, "branch", "base-version", version_commit)
    _git(
        context.root,
        "switch",
        "-c",
        "pr-head",
        lineage["baseline_commit"],
    )
    (context.root / "pr.txt").write_text("pull request\n", encoding="utf-8")
    _git(context.root, "add", "pr.txt")
    _git(context.root, "commit", "-m", "pull request")
    pr_head = _git(context.root, "rev-parse", "HEAD")
    _git(context.root, "switch", "base-version")
    _git(context.root, "merge", "--no-ff", "pr-head", "-m", "PR merge")
    merge_sha = _git(context.root, "rev-parse", "HEAD")
    _set_pull_request_environment(
        monkeypatch,
        tmp_path,
        merge_sha=merge_sha,
        candidate_sha=pr_head,
    )

    result = check_release_continuity(context)

    assert result.status is Status.BLOCKED
    assert "branch tip" in result.summary


def test_release_continuity_blocks_octopus_merge(
    tmp_path,
    monkeypatch,
):
    context, candidate = _release_repository(tmp_path)
    lineage = json.loads(
        (context.root / ".release-lineage.json").read_text(encoding="utf-8")
    )
    _git(context.root, "branch", "candidate", candidate)
    for branch in ("integration-a", "integration-b"):
        _git(context.root, "switch", "-c", branch, lineage["baseline_commit"])
        (context.root / f"{branch}.txt").write_text(branch, encoding="utf-8")
        _git(context.root, "add", f"{branch}.txt")
        _git(context.root, "commit", "-m", branch)
    _git(context.root, "switch", "integration-a")
    _git(
        context.root,
        "merge",
        "--no-ff",
        "candidate",
        "integration-b",
        "-m",
        "octopus merge",
    )
    merge_sha = _git(context.root, "rev-parse", "HEAD")
    _set_pull_request_environment(
        monkeypatch,
        tmp_path,
        merge_sha=merge_sha,
        candidate_sha=candidate,
    )

    result = check_release_continuity(context)

    assert result.status is Status.BLOCKED
    assert "branch tip" in result.summary
