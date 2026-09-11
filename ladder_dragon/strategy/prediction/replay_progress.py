# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve complete offline paths without accepting partial selection.
"""Bounded, input-bound path checkpoints and safe replay progress."""

from __future__ import annotations

import hashlib
from pathlib import Path
import time

from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json
from ladder_dragon.strategy.prediction.historical_policy import fingerprint

MAX_CHECKPOINTS = 768
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024


def implementation_identity() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "bin/replay_historical_entries.py",
        root / "ladder_dragon/strategy/depth_segments.py",
        root / "ladder_dragon/strategy/market_replay.py",
        root / "ladder_dragon/strategy/entry_veto_signal.py",
        *[Path(__file__).with_name(name) for name in (
            "historical_entry_replay.py", "historical_execution.py",
            "historical_policy.py", "context_journal.py", "replay_progress.py",
        )],
    ]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def progress(directory: Path, status: str, **counts: int) -> None:
    """Never expose source paths, prices, context rows, or exception text."""
    atomic_json(directory / "status.json", {
        "schema_version": 2, "mode": "SHADOW", "apply_allowed": False,
        "status": status, "updated_at_ms": time.time_ns() // 1_000_000,
        "operator_review_ready": False, **counts,
    }, replace=True)


class PathCheckpoint:
    """Only complete path results can survive a bounded worker restart."""

    def __init__(self, directory: Path, binding: dict):
        self.directory = directory / ".path-checkpoints"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError("checkpoint directory is linked")
        entries = list(self.directory.iterdir())
        if len(entries) > MAX_CHECKPOINTS or any(
            p.is_symlink() or not p.is_file() for p in entries
        ):
            raise ValueError("checkpoint inventory is invalid or full")
        self.used = sum(p.stat().st_size for p in entries)
        self.count = len(entries)
        if self.used > MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint byte capacity reached")
        self.binding = {**binding, "implementation": implementation_identity()}
        self.path = self.directory / (fingerprint(self.binding) + ".json")

    def read(self) -> list[dict] | None:
        if not self.path.exists():
            return None
        payload = bounded_json(self.path)
        digest = payload.pop("checkpoint_sha256", None)
        if fingerprint(payload) != digest or payload.get("binding") != self.binding:
            raise ValueError("checkpoint identity differs")
        reports = payload.get("reports")
        self._validate(reports)
        return reports

    def _validate(self, reports) -> None:
        if not isinstance(reports, list) or len(reports) != len(self.binding["jobs"]):
            raise ValueError("checkpoint report count differs")
        for report, job in zip(reports, self.binding["jobs"]):
            if not isinstance(report, dict) or (
                report.get("status") != "COMPLETE_SELECTION_REPLAY"
                or report.get("policy") != job["policy"]
                or report.get("context_sha256") != job["context_sha256"]
                or report.get("mode") != "SHADOW"
                or report.get("apply_allowed") is not False
                or any(report.get(key + "_ts_ms") != self.binding["path"][key + "_ms"]
                       for key in ("start", "entry_end", "end", "cutoff"))
            ):
                raise ValueError("checkpoint report contract differs")

    def write(self, reports: list[dict]) -> None:
        self._validate(reports)
        if self.count >= MAX_CHECKPOINTS:
            raise ValueError("checkpoint file capacity reached")
        payload = {"schema_version": 1, "binding": self.binding, "reports": reports}
        payload["checkpoint_sha256"] = fingerprint(payload)
        # Use the same strict byte limit as the checkpoint reader.
        import json
        size = len((json.dumps(payload, sort_keys=True) + "\n").encode())
        if size > 2 * 1024 * 1024 or self.used + size > MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint byte capacity reached")
        atomic_json(self.path, payload)
