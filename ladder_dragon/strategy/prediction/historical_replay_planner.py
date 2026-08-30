# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: draft deterministic historical replay windows without importing evidence.
"""Create review-only replay requests from continuous public history."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json
from ladder_dragon.strategy.prediction.context_journal import export_context
from ladder_dragon.strategy.prediction.entry_veto_replay import candidate_grid
from ladder_dragon.strategy.prediction.episode_semantics import (
    execution_model_contract,
    v23_evidence_semantics_contract,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


BLOCK_COUNT = 4
PATHS_PER_BLOCK = 3
SIGNAL_WARMUP_MS = 300_000
PATH_ENTRY_WINDOW_MS = 300_000
TERMINAL_TAIL_MS = 6 * 60 * 60_000 + 1_000
INDEPENDENCE_SPACING_MS = 6 * 60 * 60_000
MINIMUM_INDEPENDENT_PATHS = 12
MAXIMUM_DRAFTS = 256
MAXIMUM_CONTEXT_CANDIDATES = 256
PROVIDER_CONNECTION_MAX_MS = 24 * 60 * 60_000
COHORT_CONTRACT = "provider_bounded_disjoint_paths_v1"
SELECTION_COHORT_MARKER = "selection-cohort.json"

PathWindow = tuple[int, int, int, list[tuple[Path, dict]]]
ContextPath = tuple[PathWindow, dict]


def _continuous(rows: list[tuple[Path, dict]]) -> bool:
    """Check metadata boundaries; the runner later verifies every source byte."""
    for (_, previous), (_, current) in zip(rows, rows[1:]):
        if not (
            current.get("schema_version") == previous.get("schema_version") == 2
            and current.get("session_id") == previous.get("session_id")
            and current.get("symbol") == previous.get("symbol")
            and current.get("segment_index") == previous.get("segment_index") + 1
            and current.get("previous_archive_sha256") == previous.get("archive_sha256")
            and current.get("first_snapshot_update_id") == previous.get("last_update_id")
            and current.get("first_trade_id") == previous.get("last_trade_id")
            and current.get("started_at_ms") == previous.get("finished_at_ms")
        ):
            return False
    return True


def _chains(directory: Path, symbol: str) -> list[list[tuple[Path, dict]]]:
    """Return every complete session without joining history across a gap."""
    groups: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    sidecars = sorted(directory.glob("*.jsonl.metadata.json"))
    if len(sidecars) > 10_000:
        raise ValueError("historical planner archive capacity reached")
    for sidecar in sidecars:
        metadata = bounded_json(sidecar)
        if (
            metadata.get("schema_version") != 2
            or metadata.get("contains_secrets") is not False
            or metadata.get("symbol") != symbol
        ):
            continue
        archive = sidecar.with_suffix("").with_suffix("")
        if not archive.is_file():
            continue
        groups[str(metadata.get("session_id") or "")].append((archive, metadata))
    candidates: list[list[tuple[Path, dict]]] = []
    for rows in groups.values():
        rows.sort(key=lambda item: int(item[1]["segment_index"]))
        if rows and _continuous(rows):
            candidates.append(rows)
    return sorted(
        candidates,
        key=lambda rows: int(rows[-1][1]["finished_at_ms"]),
    )


def _provider_design() -> dict[str, object]:
    """Prove each path fits inside the provider connection lifetime."""
    path_duration_ms = (
        SIGNAL_WARMUP_MS + PATH_ENTRY_WINDOW_MS + TERMINAL_TAIL_MS
    )
    reachable = bool(
        path_duration_ms < PROVIDER_CONNECTION_MAX_MS
        and BLOCK_COUNT * PATHS_PER_BLOCK >= MINIMUM_INDEPENDENT_PATHS
    )
    return {
        "cohort_contract": COHORT_CONTRACT,
        "provider_connection_max_ms": PROVIDER_CONNECTION_MAX_MS,
        "path_duration_ms": path_duration_ms,
        "paths_per_block": PATHS_PER_BLOCK,
        "required_blocks": BLOCK_COUNT,
        "required_independent_paths": MINIMUM_INDEPENDENT_PATHS,
        "reachable": reachable,
    }


def _complete_paths(
    chains: Iterable[list[tuple[Path, dict]]],
    *,
    maximum_paths: int = MINIMUM_INDEPENDENT_PATHS,
) -> list[PathWindow]:
    """Select source-disjoint paths that never cross a reconnect boundary."""
    if not 1 <= maximum_paths <= MAXIMUM_CONTEXT_CANDIDATES:
        raise ValueError("historical path candidate limit is invalid")
    candidates: list[PathWindow] = []
    for chain in chains:
        cursor = 0
        while cursor < len(chain):
            start = int(chain[cursor][1]["started_at_ms"]) + SIGNAL_WARMUP_MS
            entry_end = start + PATH_ENTRY_WINDOW_MS
            end = entry_end + TERMINAL_TAIL_MS
            terminal_index = next(
                (
                    index
                    for index in range(cursor, len(chain))
                    if int(chain[index][1]["finished_at_ms"]) >= end
                ),
                None,
            )
            if terminal_index is None:
                break
            candidates.append(
                (start, entry_end, end, chain[cursor : terminal_index + 1])
            )
            # A source segment belongs to one independent path only.
            cursor = terminal_index + 1

    selected: list[PathWindow] = []
    next_start: int | None = None
    for path in sorted(candidates, key=lambda row: row[0], reverse=True):
        if next_start is None or path[2] < next_start:
            selected.append(path)
            next_start = path[0]
            if len(selected) == maximum_paths:
                break
    return list(reversed(selected))


def _complete_blocks(paths: list[ContextPath]) -> list[list[ContextPath]]:
    """Group complete paths into disjoint chronological stability blocks."""
    complete = len(paths) // PATHS_PER_BLOCK
    if complete < BLOCK_COUNT:
        return [
            paths[index * PATHS_PER_BLOCK : (index + 1) * PATHS_PER_BLOCK]
            for index in range(complete)
        ]
    paths = paths[-BLOCK_COUNT * PATHS_PER_BLOCK :]
    return [
        paths[index * PATHS_PER_BLOCK : (index + 1) * PATHS_PER_BLOCK]
        for index in range(BLOCK_COUNT)
    ]


def _context_reason(exc: ValueError) -> str:
    """Map source diagnostics to bounded operator-safe progress reasons."""
    reasons = {
        "past historical context unavailable": "PAST_CONTEXT_UNAVAILABLE",
        "context interval contains unavailable evidence": "CONTEXT_UNAVAILABLE",
        "context classifier differs or interval has a gap": "CONTEXT_GAP_OR_CLASSIFIER",
        "context does not cover the terminal observation tail": "CONTEXT_TAIL_UNAVAILABLE",
        "context chain or session differs": "CONTEXT_CHAIN_DIFFERENT",
    }
    return reasons.get(str(exc), "CONTEXT_INVALID")


def context_ready_paths(
    chains: Iterable[list[tuple[Path, dict]]],
    context_db: Path,
    *,
    started_after_ms: int = 0,
    excluded_source_sha256s: frozenset[str] = frozenset(),
    maximum_ready_paths: int = MINIMUM_INDEPENDENT_PATHS,
) -> tuple[list[ContextPath], dict[str, object]]:
    """Return only paths whose complete source-owned context exports safely."""
    if not 1 <= maximum_ready_paths <= MAXIMUM_CONTEXT_CANDIDATES:
        raise ValueError("historical context-ready path limit is invalid")
    classifier = fingerprint(
        v23_evidence_semantics_contract()["regime_classifier"]
    )
    candidates = _complete_paths(
        chains, maximum_paths=MAXIMUM_CONTEXT_CANDIDATES
    )
    eligible = [
        path for path in candidates
        if path[0] > started_after_ms
        and not excluded_source_sha256s.intersection(
            str(metadata["archive_sha256"])
            for _archive, metadata in path[3]
        )
    ]
    ready: list[ContextPath] = []
    reasons: Counter[str] = Counter()
    identity: tuple[str, str] | None = None
    checked = 0
    # Inspect newest paths first. Stop once the immutable cohort is complete.
    for path in reversed(eligible):
        checked += 1
        start, _entry_end, end, _selected = path
        try:
            exported = export_context(
                context_db,
                symbol="SOLUSDT",
                classifier_fingerprint=classifier,
                start_ms=start,
                end_ms=end,
                cutoff_ms=end,
            )
        except ValueError as exc:
            reasons[_context_reason(exc)] += 1
            continue
        row = exported["context"][0]
        current = (
            str(row["classifier_fingerprint"]),
            str(row["panic_source_fingerprint"]),
        )
        if identity is None:
            identity = current
        if current != identity:
            reasons["CONTEXT_SEMANTICS_DIFFERENT"] += 1
            continue
        ready.append((path, row))
        if len(ready) == maximum_ready_paths:
            break
    ready.reverse()
    return ready, {
        "l2_complete_independent_paths": min(
            len(eligible), maximum_ready_paths
        ),
        "context_checked_paths": checked,
        "context_ready_independent_paths": len(ready),
        "context_rejected_path_counts": dict(sorted(reasons.items())),
    }


def _request_sources(request: Mapping[str, object]) -> list[str]:
    values: list[str] = []
    for path in request["paths"]:
        values.extend(str(row["sha256"]) for row in path["archives"])
    return values


def _existing_draft_identities(draft_directory: Path) -> set[str]:
    """Validate every existing draft before it can freeze the cohort."""
    drafts = sorted(
        path for path in draft_directory.glob("*.json")
        if path.name != "status.json"
    )
    if len(drafts) > MAXIMUM_DRAFTS:
        raise ValueError("historical replay draft capacity reached")
    identities: set[str] = set()
    for path in drafts:
        payload = bounded_json(path)
        identity = fingerprint(payload)
        if path.stem != identity or identity in identities:
            raise ValueError("historical replay draft identity differs")
        identities.add(identity)
    return identities


def _policy(candidate: Mapping[str, object], context: Mapping[str, object]) -> dict:
    model = execution_model_contract()
    return {
        "symbol": "SOLUSDT",
        "entry_gap_bps": "48",
        "take_profit_bps": "80",
        "stop_trigger_bps": "88.5",
        "stop_limit_bps": "103.5",
        "notional_quote": "6",
        "entry_ttl_ms": 5_400_000,
        "holding_ms": 21_600_000,
        "cadence_ms": 300_000,
        "latency_ms": int(model["latency_ms"]),
        "cancel_latency_ms": int(candidate["cancel_latency_ms"]),
        "stop_grace_ms": int(model["stop_unfilled_grace_ms"]),
        "market_impact_bps": str(model["emergency_market_impact_bps"]),
        "maximum_event_gap_ms": int(model["maximum_event_gap_ms"]),
        "allowed_regimes": list(
            v23_evidence_semantics_contract()["executable_entry_regimes"]
        ),
        "classifier_fingerprint": str(context["classifier_fingerprint"]),
        "panic_source_fingerprint": str(context["panic_source_fingerprint"]),
        "veto_price_bps": str(candidate["prefill_price_change_max_bps"]),
        "veto_signed_flow": str(candidate["prefill_signed_trade_flow_max"]),
        "veto_ofi": str(candidate["prefill_order_flow_imbalance_max"]),
        "signal_window_ms": int(candidate["signal_window_ms"]),
        "maximum_attempts": 10_000,
    }


def plan_replay_drafts(
    archive_directory: Path,
    draft_directory: Path,
    context_db: Path,
) -> dict[str, object]:
    """Publish drafts only after a reachable, disjoint block cohort exists."""
    draft_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    design = _provider_design()
    if design["reachable"] is not True:
        return {
            "schema_version": 3,
            "mode": "SHADOW",
            "apply_allowed": False,
            "status": "DESIGN_UNREACHABLE",
            "draft_count": 0,
            "complete_blocks": 0,
            "complete_independent_paths": 0,
            **design,
        }
    chains = _chains(archive_directory, "SOLUSDT")
    paths, progress = context_ready_paths(chains, context_db)
    blocks = _complete_blocks(paths)
    if len(blocks) < BLOCK_COUNT:
        return {
            "schema_version": 3,
            "mode": "SHADOW",
            "apply_allowed": False,
            "status": "COLLECTING_CONTEXT_READY_PATHS",
            "draft_count": 0,
            "required_blocks": BLOCK_COUNT,
            "complete_blocks": len(blocks),
            "complete_independent_paths": len(paths),
            "continuous_sessions": len(chains),
            **progress,
            **design,
        }
    windows = []
    for block_index, block in enumerate(blocks):
        contexts = [context for _path, context in block]
        identities = {
            (
                row["classifier_fingerprint"],
                row["panic_source_fingerprint"],
            )
            for row in contexts
        }
        if len(identities) != 1:
            raise ValueError("historical path semantics differ inside a block")
        windows.append((
            block_index,
            [path for path, _context in block],
            contexts[0],
        ))

    requests: dict[str, dict[str, object]] = {}
    for candidate in candidate_grid():
        for block_index, block, context in windows:
            request = {
                "request_schema_version": 2,
                "cohort_contract": COHORT_CONTRACT,
                "stability_block_index": block_index,
                "policy": _policy(candidate, context),
                "paths": [
                    {
                        "archives": [
                            {
                                "path": str(path),
                                "sha256": metadata["archive_sha256"],
                            }
                            for path, metadata in selected
                        ],
                        "start_ms": start,
                        "entry_end_ms": entry_end,
                        "end_ms": end,
                        "cutoff_ms": end,
                    }
                    for start, entry_end, end, selected in block
                ],
            }
            requests[fingerprint(request)] = request
    if len(requests) > MAXIMUM_DRAFTS:
        raise ValueError("historical replay draft capacity reached")
    marker_path = draft_directory.parent / SELECTION_COHORT_MARKER
    marker = {
        "schema_version": 1,
        "mode": "SHADOW_SELECTION",
        "apply_allowed": False,
        "cohort_contract": COHORT_CONTRACT,
        "request_sha256s": sorted(requests),
        "source_archive_sha256s": sorted({
            source
            for request in requests.values()
            for source in _request_sources(request)
        }),
        "cutoff_ts_ms": max(path[0][2] for block in blocks for path in block),
    }
    marker["cohort_sha256"] = fingerprint(marker)
    existing_ids = _existing_draft_identities(draft_directory)
    if marker_path.exists():
        frozen = bounded_json(marker_path)
        return {
            "schema_version": 3,
            "mode": "SHADOW",
            "apply_allowed": False,
            "status": "DRAFT_COHORT_FROZEN_FOR_REVIEW",
            "draft_count": len(existing_ids),
            "created_drafts": 0,
            "required_blocks": BLOCK_COUNT,
            "complete_blocks": len(blocks),
            "complete_independent_paths": len(paths),
            "continuous_sessions": len(chains),
            "frozen_cohort_sha256": frozen.get("cohort_sha256"),
            "current_cohort_matches_frozen": frozen == marker,
            **progress,
            **design,
            "automatic_queueing": False,
            "automatic_selection_import": False,
        }
    elif not existing_ids.issubset(requests):
        return {
            "schema_version": 3,
            "mode": "SHADOW",
            "apply_allowed": False,
            "status": "DRAFT_COHORT_REVIEW_REQUIRED",
            "draft_count": len(existing_ids),
            "created_drafts": 0,
            "required_blocks": BLOCK_COUNT,
            "complete_blocks": len(blocks),
            "complete_independent_paths": len(paths),
            "continuous_sessions": len(chains),
            **progress,
            **design,
            "automatic_queueing": False,
            "automatic_selection_import": False,
        }
    created = 0
    for identity, request in requests.items():
        if identity in existing_ids:
            continue
        atomic_json(draft_directory / f"{identity}.json", request)
        created += 1
    if not marker_path.exists():
        atomic_json(marker_path, marker)
    total = len(requests)
    return {
        "schema_version": 3,
        "mode": "SHADOW",
        "apply_allowed": False,
        "status": "DRAFTS_READY_FOR_OPERATOR_REVIEW",
        "draft_count": total,
        "created_drafts": created,
        "required_blocks": BLOCK_COUNT,
        "complete_blocks": len(blocks),
        "complete_independent_paths": len(paths),
        "continuous_sessions": len(chains),
        "frozen_cohort_sha256": marker["cohort_sha256"],
        **progress,
        **design,
        "automatic_queueing": False,
        "automatic_selection_import": False,
    }


__all__ = ["context_ready_paths", "plan_replay_drafts"]
