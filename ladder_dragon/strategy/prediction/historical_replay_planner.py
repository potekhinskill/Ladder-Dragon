# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: draft deterministic historical replay windows without importing evidence.
"""Create review-only replay requests from continuous public history."""

from __future__ import annotations

from collections import defaultdict
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
SIGNAL_WARMUP_MS = 300_000
ENTRY_WINDOW_MS = 18 * 60 * 60_000
TERMINAL_TAIL_MS = 6 * 60 * 60_000 + 1_000
INDEPENDENCE_SPACING_MS = 6 * 60 * 60_000
MINIMUM_INDEPENDENT_PATHS = 12
MAXIMUM_DRAFTS = 256


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


def _reachable_independent_paths() -> int:
    """Prove the planner can satisfy the importer before publishing work."""
    per_block = (ENTRY_WINDOW_MS - 1) // INDEPENDENCE_SPACING_MS + 1
    return BLOCK_COUNT * per_block


def _complete_blocks(
    chains: Iterable[list[tuple[Path, dict]]],
) -> list[tuple[int, int, int, list[tuple[Path, dict]]]]:
    """Select disjoint complete windows from any individually continuous session."""
    candidates: list[tuple[int, int, int, list[tuple[Path, dict]]]] = []
    for chain in chains:
        cursor = 0
        while cursor < len(chain):
            start = int(chain[cursor][1]["started_at_ms"]) + SIGNAL_WARMUP_MS
            entry_end = start + ENTRY_WINDOW_MS
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
            selected = chain[cursor : terminal_index + 1]
            candidates.append((start, entry_end, end, selected))
            # A source segment belongs to one evidence block only.
            cursor = terminal_index + 1

    # Work backwards to retain the newest maximum-size non-overlapping cohort.
    selected_blocks: list[
        tuple[int, int, int, list[tuple[Path, dict]]]
    ] = []
    next_start: int | None = None
    for block in sorted(candidates, key=lambda row: row[0], reverse=True):
        if next_start is None or block[2] < next_start:
            selected_blocks.append(block)
            next_start = block[0]
            if len(selected_blocks) == BLOCK_COUNT:
                break
    return list(reversed(selected_blocks))


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
    reachable_paths = _reachable_independent_paths()
    if reachable_paths < MINIMUM_INDEPENDENT_PATHS:
        raise ValueError("historical selection design is mathematically unreachable")
    chains = _chains(archive_directory, "SOLUSDT")
    blocks = _complete_blocks(chains)
    if len(blocks) < BLOCK_COUNT:
        return {
            "schema_version": 2,
            "mode": "SHADOW",
            "apply_allowed": False,
            "status": "COLLECTING_DISJOINT_CONTINUOUS_BLOCKS",
            "draft_count": 0,
            "required_blocks": BLOCK_COUNT,
            "complete_blocks": len(blocks),
            "continuous_sessions": len(chains),
            "maximum_reachable_independent_paths": reachable_paths,
            "required_independent_paths": MINIMUM_INDEPENDENT_PATHS,
        }
    windows = []
    for start, entry_end, end, selected in blocks:
        classifier = fingerprint(
            v23_evidence_semantics_contract()["regime_classifier"]
        )
        context = export_context(
            context_db,
            symbol="SOLUSDT",
            classifier_fingerprint=classifier,
            start_ms=start,
            end_ms=end,
            cutoff_ms=end,
        )
        windows.append((start, entry_end, end, selected, context["context"][0]))

    created = existing = 0
    for candidate in candidate_grid():
        for start, entry_end, end, selected, context in windows:
            request = {
                "policy": _policy(candidate, context),
                "archives": [
                    {"path": str(path), "sha256": metadata["archive_sha256"]}
                    for path, metadata in selected
                ],
                "start_ms": start,
                "entry_end_ms": entry_end,
                "end_ms": end,
                "cutoff_ms": end,
            }
            target = draft_directory / f"{fingerprint(request)}.json"
            if target.exists():
                if bounded_json(target) != request:
                    raise ValueError("historical replay draft identity differs")
                existing += 1
                continue
            atomic_json(target, request)
            created += 1
    total = created + existing
    if total > MAXIMUM_DRAFTS:
        raise ValueError("historical replay draft capacity reached")
    return {
        "schema_version": 2,
        "mode": "SHADOW",
        "apply_allowed": False,
        "status": "DRAFTS_READY_FOR_OPERATOR_REVIEW",
        "draft_count": total,
        "created_drafts": created,
        "required_blocks": BLOCK_COUNT,
        "continuous_sessions": len(chains),
        "maximum_reachable_independent_paths": reachable_paths,
        "required_independent_paths": MINIMUM_INDEPENDENT_PATHS,
        "automatic_queueing": False,
        "automatic_selection_import": False,
    }


__all__ = ["plan_replay_drafts"]
