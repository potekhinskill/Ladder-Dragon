#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: replay public history with immutable policy and past context inputs.
"""Generate selection-only opportunities without database or exchange writes."""

import argparse
from pathlib import Path

from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json, iter_segment_events, verified_segments
from ladder_dragon.strategy.prediction.historical_entry_replay import historical_entry_replay
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = bounded_json(args.request)
        if set(request) != {"policy", "context", "archives", "start_ms", "entry_end_ms", "end_ms", "cutoff_ms"}:
            raise ValueError("historical replay request schema mismatch")
        sources = request.pop("archives")
        if not isinstance(sources, list) or not 1 <= len(sources) <= 10000:
            raise ValueError("historical replay sources missing or oversized")
        for source in sources:
            if set(source) != {"path", "sha256"}:
                raise ValueError("historical source schema mismatch")
        segments = verified_segments(Path(source["path"]) for source in sources)
        if any(source["sha256"] != segment[1]["archive_sha256"] for source, segment in zip(sources, segments)):
            raise ValueError("historical source differs from pinned request")
        if any(meta["symbol"] != request["policy"]["symbol"] for _, meta in segments):
            raise ValueError("historical source symbol differs from policy")
        report = historical_entry_replay(iter_segment_events(segments, level_limit=1000),
                                         policy_payload=request.pop("policy"),
                                         context_rows=request.pop("context"), **request)
        report["source_sha256s"] = [meta["archive_sha256"] for _, meta in segments]
        report["report_sha256"] = fingerprint(report)
        atomic_json(args.output, report)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        # Raw source text and paths cannot leak through failure diagnostics.
        print(f"[HISTORICAL-REPLAY] status=BLOCKED error={type(exc).__name__}")
        return 2
    print(f"[HISTORICAL-REPLAY] status={report['status']} mode=SHADOW")
    return 0 if report["status"] == "COMPLETE_SELECTION_REPLAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
