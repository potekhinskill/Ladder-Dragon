#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: replay public history with immutable policy and past context inputs.
"""Generate selection-only opportunities without database or exchange writes."""

import argparse
from decimal import Decimal
from pathlib import Path
import sqlite3

from ladder_dragon.strategy.depth_segments import (
    atomic_json,
    bounded_json,
    iter_segment_events,
    verified_segments,
)
from ladder_dragon.strategy.prediction.historical_entry_replay import (
    historical_entry_replay,
    historical_entry_replays,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.context_journal import export_context
from ladder_dragon.strategy.prediction.historical_replay_planner import (
    COHORT_CONTRACT,
)


LEGACY_FIELDS = {
    "policy", "archives", "start_ms", "entry_end_ms", "end_ms", "cutoff_ms",
}
PATH_FIELDS = {
    "archives", "start_ms", "entry_end_ms", "end_ms", "cutoff_ms",
}
PATH_REQUEST_FIELDS = {
    "request_schema_version", "cohort_contract", "stability_block_index",
    "policy", "paths",
}


def _validated_segments(path: dict, policy: dict):
    if not isinstance(path, dict) or set(path) != PATH_FIELDS:
        raise ValueError("historical replay path schema mismatch")
    if any(
        type(path.get(field)) is not int
        for field in ("start_ms", "entry_end_ms", "end_ms", "cutoff_ms")
    ) or not (
        0 < path["start_ms"] < path["entry_end_ms"] < path["end_ms"]
        <= path["cutoff_ms"]
    ):
        raise ValueError("historical replay path timestamps are invalid")
    sources = path["archives"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10_000:
        raise ValueError("historical replay sources missing or oversized")
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
            raise ValueError("historical source schema mismatch")
    segments = verified_segments(Path(source["path"]) for source in sources)
    if len(segments) != len(sources) or any(
        source["sha256"] != segment[1]["archive_sha256"]
        for source, segment in zip(sources, segments)
    ):
        raise ValueError("historical source differs from pinned request")
    if any(meta["symbol"] != policy["symbol"] for _, meta in segments):
        raise ValueError("historical source symbol differs from policy")
    if not (
        int(segments[0][1]["started_at_ms"]) <= path["start_ms"]
        and path["cutoff_ms"] <= int(segments[-1][1]["finished_at_ms"])
    ):
        raise ValueError("historical path exceeds its pinned source session")
    return segments


def _combined_path_report(
    request: dict, path_reports: list[tuple[dict, dict, list[str]]]
) -> dict:
    """Combine source-disjoint path results into one stability block."""
    if len(path_reports) != 3:
        raise ValueError("historical stability block path count differs")
    reports = [row[0] for row in path_reports]
    if len({fingerprint(report["policy"]) for report in reports}) != 1:
        raise ValueError("historical stability block policies differ")
    if len({fingerprint(report["model_source_sha256s"]) for report in reports}) != 1:
        raise ValueError("historical stability block implementations differ")
    episodes = {"baseline": [], "veto": []}
    summaries = {}
    for name in episodes:
        opportunities = filled = censored = 0
        net = Decimal("0")
        for path_index, (report, _context, _hashes) in enumerate(path_reports):
            for row in report["episodes"][name]:
                item = dict(row)
                item["episode_id"] = f"path-{path_index}:{row['episode_id']}"
                episodes[name].append(item)
            summary = report["summaries"][name]
            opportunities += int(summary["opportunities"])
            filled += int(summary["filled"])
            censored += int(summary["censored"])
            net += Decimal(str(summary["net_pnl_quote"]))
        summaries[name] = {
            "opportunities": opportunities,
            "filled": filled,
            "net_pnl_quote": format(net, "f"),
            "censored": censored,
        }
    windows = []
    source_hashes = []
    for path, (_report, _context, hashes) in zip(request["paths"], path_reports):
        windows.append({
            "start_ts_ms": int(path["start_ms"]),
            "entry_end_ts_ms": int(path["entry_end_ms"]),
            "end_ts_ms": int(path["end_ms"]),
            "cutoff_ts_ms": int(path["cutoff_ms"]),
            "source_sha256s": list(hashes),
        })
        source_hashes.extend(hashes)
    if len(source_hashes) != len(set(source_hashes)):
        raise ValueError("historical stability block reuses a source")
    status = (
        "COMPLETE_SELECTION_REPLAY"
        if all(report["status"] == "COMPLETE_SELECTION_REPLAY" for report in reports)
        else "INCOMPLETE_HISTORY"
    )
    first, last = windows[0], windows[-1]
    return {
        "schema_version": 2,
        "model_contract": reports[0]["model_contract"],
        "cohort_contract": request["cohort_contract"],
        "stability_block_index": request["stability_block_index"],
        "status": status,
        "mode": "SHADOW",
        "apply_allowed": False,
        "promotion_eligible": False,
        "selection_artifact_ready": False,
        "model_source_sha256s": reports[0]["model_source_sha256s"],
        "remaining_gates": reports[0]["remaining_gates"],
        "policy": reports[0]["policy"],
        "policy_sha256": reports[0]["policy_sha256"],
        "context_sha256s": [
            fingerprint({"rows": context["context"]})
            for _report, context, _hashes in path_reports
        ],
        "context_evidence_paths": [
            context for _report, context, _hashes in path_reports
        ],
        "path_windows": windows,
        "source_sha256s": source_hashes,
        "start_ts_ms": first["start_ts_ms"],
        "entry_end_ts_ms": last["entry_end_ts_ms"],
        "end_ts_ms": last["end_ts_ms"],
        "cutoff_ts_ms": last["cutoff_ts_ms"],
        "summaries": summaries,
        "episodes": episodes,
    }


def _run_path_request_batch(
    requests: list[tuple[Path, Path]], *, context_db: Path
) -> list[dict]:
    loaded = [bounded_json(request_path) for request_path, _ in requests]
    if any(set(request) != PATH_REQUEST_FIELDS for request in loaded):
        raise ValueError("historical path request schema mismatch")
    common = {
        key: loaded[0][key]
        for key in (
            "request_schema_version", "cohort_contract",
            "stability_block_index", "paths",
        )
    }
    if (
        common["request_schema_version"] != 2
        or common["cohort_contract"] != COHORT_CONTRACT
        or type(common["stability_block_index"]) is not int
        or not 0 <= common["stability_block_index"] < 4
        or not isinstance(common["paths"], list)
        or len(common["paths"]) != 3
        or any(
            any(request[key] != value for key, value in common.items())
            for request in loaded[1:]
        )
    ):
        raise ValueError("historical path request identity differs")
    per_policy: list[list[tuple[dict, dict, list[str]]]] = [
        [] for _request in loaded
    ]
    previous_end = -1
    observed_hashes: set[str] = set()
    for path in common["paths"]:
        if (
            not isinstance(path, dict)
            or type(path.get("start_ms")) is not int
            or path["start_ms"] <= previous_end
        ):
            raise ValueError("historical paths overlap or are unordered")
        segments = _validated_segments(path, loaded[0]["policy"])
        hashes = [meta["archive_sha256"] for _, meta in segments]
        if observed_hashes & set(hashes):
            raise ValueError("historical paths reuse a source")
        observed_hashes.update(hashes)
        previous_end = int(path["end_ms"])
        jobs = []
        contexts = []
        for request in loaded:
            policy = request["policy"]
            if any(meta["symbol"] != policy["symbol"] for _, meta in segments):
                raise ValueError("historical source symbol differs from policy")
            evidence = export_context(
                context_db,
                symbol=policy["symbol"],
                classifier_fingerprint=policy["classifier_fingerprint"],
                start_ms=path["start_ms"],
                end_ms=path["end_ms"],
                cutoff_ms=path["cutoff_ms"],
            )
            contexts.append(evidence)
            jobs.append((policy, evidence["context"]))
        reports = historical_entry_replays(
            iter_segment_events(segments, level_limit=1000),
            jobs=jobs,
            start_ms=path["start_ms"],
            entry_end_ms=path["entry_end_ms"],
            end_ms=path["end_ms"],
            cutoff_ms=path["cutoff_ms"],
        )
        for index, (report, context) in enumerate(zip(reports, contexts)):
            per_policy[index].append((report, context, hashes))
    output = []
    for request, parts, (_request_path, output_path) in zip(
        loaded, per_policy, requests
    ):
        report = _combined_path_report(request, parts)
        report["report_sha256"] = fingerprint(report)
        atomic_json(output_path, report)
        output.append(report)
    return output


def run_replay_request(
    request_path: Path, output_path: Path, *, context_db: Path | None = None
) -> dict:
    """Validate one pinned request and publish one immutable report."""
    request = bounded_json(request_path)
    if request.get("request_schema_version") == 2:
        if context_db is None:
            raise ValueError("historical path replay requires source-owned context")
        return _run_path_request_batch(
            [(request_path, output_path)], context_db=context_db
        )[0]
    if set(request) != (LEGACY_FIELDS if context_db else LEGACY_FIELDS | {"context"}):
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


def run_replay_request_batch(
    requests: list[tuple[Path, Path]],
    *,
    context_db: Path,
) -> list[dict]:
    """Replay one source block for many policies without reparsing its L2 stream."""
    if not 1 <= len(requests) <= 64:
        raise ValueError("historical replay request batch is invalid")
    loaded = [bounded_json(request_path) for request_path, _ in requests]
    if all(request.get("request_schema_version") == 2 for request in loaded):
        return _run_path_request_batch(requests, context_db=context_db)
    if any(set(request) != LEGACY_FIELDS for request in loaded):
        raise ValueError("historical replay request schema mismatch")
    common = {
        key: loaded[0][key]
        for key in ("archives", "start_ms", "entry_end_ms", "end_ms", "cutoff_ms")
    }
    if any(
        any(request[key] != value for key, value in common.items())
        for request in loaded[1:]
    ):
        raise ValueError("historical replay batch source windows differ")
    sources = common["archives"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10_000:
        raise ValueError("historical replay sources missing or oversized")
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
            raise ValueError("historical source schema mismatch")
    segments = verified_segments(Path(source["path"]) for source in sources)
    if any(
        source["sha256"] != segment[1]["archive_sha256"]
        for source, segment in zip(sources, segments)
    ):
        raise ValueError("historical source differs from pinned request")
    jobs = []
    contexts = []
    for request in loaded:
        policy = request["policy"]
        if any(meta["symbol"] != policy["symbol"] for _, meta in segments):
            raise ValueError("historical source symbol differs from policy")
        evidence = export_context(
            context_db,
            symbol=policy["symbol"],
            classifier_fingerprint=policy["classifier_fingerprint"],
            start_ms=common["start_ms"],
            end_ms=common["end_ms"],
            cutoff_ms=common["cutoff_ms"],
        )
        contexts.append(evidence)
        jobs.append((policy, evidence["context"]))
    reports = historical_entry_replays(
        iter_segment_events(segments, level_limit=1000),
        jobs=jobs,
        start_ms=common["start_ms"],
        entry_end_ms=common["entry_end_ms"],
        end_ms=common["end_ms"],
        cutoff_ms=common["cutoff_ms"],
    )
    source_hashes = [meta["archive_sha256"] for _, meta in segments]
    for report, evidence, (_, output_path) in zip(reports, contexts, requests):
        report["source_sha256s"] = source_hashes
        report["context_evidence"] = evidence
        report["report_sha256"] = fingerprint(report)
        atomic_json(output_path, report)
    return reports


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
