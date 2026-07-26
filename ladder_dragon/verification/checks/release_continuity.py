# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: fail closed when release versions, tags, or ancestry lose continuity.
"""Strict release lineage verification after an explicit historical baseline."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import time

from ladder_dragon.verification.models import (
    CheckResult,
    CheckSpec,
    HarnessContext,
    Status,
)


SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")
VERSION_SOURCE_RE = re.compile(
    r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"\s*$',
    re.MULTILINE,
)
README_VERSION_RE = re.compile(
    r"Current product version:\s*\*\*(\d+\.\d+\.\d+)\*\*"
)
CHANGELOG_VERSION_RE = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\] — \d{4}-\d{2}-\d{2}\s*$",
    re.MULTILINE,
)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LINEAGE_FILE = ".release-lineage.json"


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(version)
    if match is None:
        raise ValueError("release version is not semantic")
    return tuple(int(part) for part in match.groups())


def _is_direct_successor(previous: str, current: str) -> bool:
    before = _version_tuple(previous)
    after = _version_tuple(current)
    if after[0] == before[0] and after[1] == before[1]:
        return after[2] == before[2] + 1
    if after[0] == before[0] and after[1] == before[1] + 1:
        return after[2] == 0
    return (
        after[0] == before[0] + 1
        and after[1] == 0
        and after[2] == 0
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()


def _tag_exists(root: Path, tag: str) -> bool:
    completed = subprocess.run(
        ("git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            completed.returncode, completed.args
        )
    return completed.returncode == 0


def _source_version(text: str) -> str:
    match = VERSION_SOURCE_RE.search(text)
    if match is None:
        raise ValueError("canonical product version is unavailable")
    return match.group(1)


def _version_at(root: Path, ref: str) -> str:
    return _source_version(_git(root, "show", f"{ref}:product_version.py"))


def _blocked(
    started: float,
    reason: str,
    metrics: dict[str, object] | None = None,
) -> CheckResult:
    return CheckResult(
        name="release_continuity",
        status=Status.BLOCKED,
        required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=reason,
        exit_code=2,
        metrics=metrics or {},
    )


def check_release_continuity(context: HarnessContext) -> CheckResult:
    """Validate version/tag ancestry and emit the included-commit manifest."""
    started = time.monotonic()
    root = context.root
    try:
        lineage = json.loads(
            (root / LINEAGE_FILE).read_text(encoding="utf-8")
        )
        if not isinstance(lineage, dict):
            raise ValueError("release lineage is not an object")
        baseline_version = str(lineage["baseline_version"])
        baseline_tag = str(lineage["baseline_tag"])
        baseline_commit = str(lineage["baseline_commit"]).lower()
        if (
            lineage.get("schema_version") != 1
            or lineage.get("policy")
            != "strict_linear_releases_after_baseline"
            or baseline_tag != f"v{baseline_version}"
            or not FULL_SHA_RE.fullmatch(baseline_commit)
        ):
            raise ValueError("release lineage baseline is invalid")

        current_version = _source_version(
            (root / "product_version.py").read_text(encoding="utf-8")
        )
        readme_match = README_VERSION_RE.search(
            (root / "README.md").read_text(encoding="utf-8")
        )
        changelog_versions = CHANGELOG_VERSION_RE.findall(
            (root / "CHANGELOG.md").read_text(encoding="utf-8")
        )
        if (
            readme_match is None
            or readme_match.group(1) != current_version
            or not changelog_versions
            or changelog_versions[0] != current_version
        ):
            return _blocked(
                started,
                "product version, README and CHANGELOG are not synchronized",
            )

        head = _git(root, "rev-parse", "HEAD").lower()
        resolved_baseline = _git(
            root, "rev-list", "-n", "1", baseline_tag
        ).lower()
        if resolved_baseline != baseline_commit:
            return _blocked(
                started, "release lineage baseline tag or commit differs"
            )
        if _git(root, "cat-file", "-t", f"refs/tags/{baseline_tag}") != "tag":
            return _blocked(started, "release lineage baseline tag is not annotated")
        _git(root, "merge-base", "--is-ancestor", baseline_commit, head)

        tagged: list[tuple[tuple[int, int, int], str, str]] = []
        for raw_tag in _git(
            root, "tag", "--merged", "HEAD", "--list", "v*"
        ).splitlines():
            match = TAG_RE.fullmatch(raw_tag)
            if match is None:
                continue
            version = match.group(1)
            if _version_tuple(version) < _version_tuple(baseline_version):
                continue
            commit = _git(root, "rev-list", "-n", "1", raw_tag).lower()
            if _git(root, "cat-file", "-t", f"refs/tags/{raw_tag}") != "tag":
                return _blocked(
                    started, f"release tag {raw_tag} is not annotated"
                )
            if _version_at(root, f"{raw_tag}^{{commit}}") != version:
                return _blocked(
                    started,
                    f"release tag {raw_tag} points to a different product version",
                )
            tagged.append((_version_tuple(version), raw_tag, commit))
        tagged.sort()
        if not tagged or tagged[0][1] != baseline_tag:
            return _blocked(started, "strict release lineage baseline is missing")

        for previous, current in zip(tagged, tagged[1:]):
            previous_version = previous[1][1:]
            current_version_tag = current[1][1:]
            if not _is_direct_successor(
                previous_version, current_version_tag
            ):
                return _blocked(
                    started,
                    f"release tag skipped after {previous[1]}",
                )
            _git(
                root,
                "merge-base",
                "--is-ancestor",
                previous[2],
                current[2],
            )

        latest_version = tagged[-1][1][1:]
        latest_tag = tagged[-1][1]
        latest_commit = tagged[-1][2]
        is_candidate = current_version != latest_version
        if is_candidate:
            if not _is_direct_successor(latest_version, current_version):
                return _blocked(
                    started,
                    f"candidate version must directly follow {latest_version}",
                )
            candidate_tag = f"v{current_version}"
            if _tag_exists(root, candidate_tag):
                return _blocked(
                    started,
                    f"candidate tag {candidate_tag} exists outside HEAD lineage",
                )
            version_commits = _git(
                root,
                "log",
                "--format=%H",
                f"{latest_tag}..HEAD",
                "--",
                "product_version.py",
            ).splitlines()
            head_parents = _git(
                root, "rev-list", "--parents", "-n", "1", "HEAD"
            ).split()[1:]
            permitted_final_commits = {head}
            if len(head_parents) >= 2:
                # GitHub pull_request workflows test a synthetic merge commit;
                # the candidate tip is one of its direct parents.
                permitted_final_commits.update(head_parents)
            if (
                len(version_commits) != 1
                or version_commits[0] not in permitted_final_commits
            ):
                return _blocked(
                    started,
                    "candidate version must be bumped once at the branch tip",
                )
            previous_version = latest_version
            previous_tag = latest_tag
            previous_sha = latest_commit
        else:
            current_tag = tagged[-1]
            if current_tag[2] != head:
                return _blocked(
                    started,
                    "commits exist after the current release tag without a version bump",
                )
            if len(tagged) == 1:
                previous_version = None
                previous_tag = None
                previous_sha = None
            else:
                previous_version = tagged[-2][1][1:]
                previous_tag = tagged[-2][1]
                previous_sha = tagged[-2][2]

        required_versions = {row[1][1:] for row in tagged}
        required_versions.add(current_version)
        missing_changelog = sorted(
            required_versions.difference(changelog_versions),
            key=_version_tuple,
        )
        if missing_changelog:
            return _blocked(
                started,
                "strict release tags are missing from CHANGELOG",
            )

        range_start = previous_tag or f"{head}^"
        included_commits = _git(
            root,
            "rev-list",
            "--reverse",
            f"{range_start}..{head}",
        ).splitlines()
        if not included_commits:
            included_commits = [head]
        metrics: dict[str, object] = {
            "baseline_version": baseline_version,
            "previous_version": previous_version,
            "previous_sha": previous_sha,
            "current_version": current_version,
            "current_sha": head,
            "candidate": is_candidate,
            "included_commits": included_commits,
        }
        return CheckResult(
            name="release_continuity",
            status=Status.PASS,
            required=True,
            duration_ms=int((time.monotonic() - started) * 1000),
            summary="release versions, annotated tags and ancestry are continuous",
            exit_code=0,
            metrics=metrics,
        )
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ):
        return _blocked(
            started,
            "release continuity evidence is unavailable or invalid",
        )


def release_continuity_checks(
    context: HarnessContext,
) -> list[CheckSpec]:
    return [
        CheckSpec(
            name="release_continuity",
            check=check_release_continuity,
        )
    ]
