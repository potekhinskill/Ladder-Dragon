#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: replay public history with immutable policy and past context inputs.
"""Generate selection-only opportunities without database or exchange writes."""

import argparse
from pathlib import Path
import sqlite3

from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json, iter_segment_events, verified_segments
from ladder_dragon.strategy.prediction.historical_entry_replay import historical_entry_replay
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.context_journal import export_context


def run_replay_request(
    request_path: Path, output_path: Path, *, context_db: Path | None = None
) -> dict:
    """Validate one pinned request and publish one immutable report."""
    request = bounded_json(request_path)
    fields = {"policy", "archives", "start_ms", "entry_end_ms", "end_ms", "cutoff_ms"}
    if set(request) != (fields if context_db else fields | {"context"}):
        raise ValueError("historical replay request schema mismatch")
    sources = request.pop("archives")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10000:
        raise ValueError("historical replay sources missing or oversized")
    for source in sources:
        if set(source) != {"path", "sha256"}:
            raise ValueError("historical source schema mismatch")
    segments = verified_segments(Path(source["path"]) for source in sources)
    if any(
        source["sha256"] != segment[1]["archive_sha256"]
        for source, segment in zip(sources, segments)
    ):
        raise ValueError("historical source differs from pinned request")
    if any(meta["symbol"] != request["policy"]["symbol"] for _, meta in segments):
        raise ValueError("historical source symbol differs from policy")
    context_evidence = None
    if context_db:
        context_evidence = export_context(
            context_db, symbol=request["policy"]["symbol"],
            classifier_fingerprint=request["policy"]["classifier_fingerprint"],
            start_ms=request["start_ms"], end_ms=request["end_ms"],
            cutoff_ms=request["cutoff_ms"],
        )
        request["context"] = context_evidence["context"]
    report = historical_entry_replay(
        iter_segment_events(segments, level_limit=1000),
        policy_payload=request.pop("policy"),
        context_rows=request.pop("context"),
        **request,
    )
    report["source_sha256s"] = [meta["archive_sha256"] for _, meta in segments]
    if context_evidence is not None:
        report["context_evidence"] = context_evidence
    report["report_sha256"] = fingerprint(report)
    atomic_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-db", type=Path, help="Read source-owned context without modifying its journal")
    args = parser.parse_args()
    try:
        report = run_replay_request(
            args.request, args.output, context_db=args.context_db
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError, sqlite3.Error) as exc:
        # Raw source text and paths cannot leak through failure diagnostics.
        print(f"[HISTORICAL-REPLAY] status=BLOCKED error={type(exc).__name__}")
        return 2
    print(f"[HISTORICAL-REPLAY] status={report['status']} mode=SHADOW")
    return 0 if report["status"] == "COMPLETE_SELECTION_REPLAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
