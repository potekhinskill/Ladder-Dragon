# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze post-selection L2 paths for v23 confirmation review.
"""Plan a disjoint confirmation cohort from one immutable v23 manifest."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import time
from typing import Mapping

from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json
from ladder_dragon.strategy.prediction.episode_semantics import (
    execution_model_contract,
)
from ladder_dragon.strategy.prediction.episode_expectancy import (
    V23_FIXED_CONFIRMATION_PATHS,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_replay_planner import (
    COHORT_CONTRACT,
    MAXIMUM_CONTEXT_CANDIDATES,
    MAXIMUM_DRAFTS,
    PATHS_PER_BLOCK,
    SIGNAL_WARMUP_MS,
    PATH_ENTRY_WINDOW_MS,
    PROVIDER_CONNECTION_MAX_MS,
    TERMINAL_TAIL_MS,
    _chains,
    _existing_draft_identities,
    _request_sources,
    context_ready_paths,
)
from ladder_dragon.strategy.prediction.v23_confirmation import (
    find_active_v23_manifest,
    load_v23_selection_artifact,
)


D = Decimal
CONFIRMATION_COHORT_MARKER = "confirmation-cohort.json"
CONFIRMATION_BLOCK_DIRECTORY = "confirmation-blocks"
CONFIRMATION_CAPACITY_RESERVE_PATHS = 3


def _integer(criteria: Mapping[str, object], field: str) -> int:
    value = criteria.get(field)
    if type(value) is not int or value <= 0:
        raise ValueError("v23 confirmation criteria are invalid")
    return value


def _rate(metrics: Mapping[str, object], field: str) -> Decimal:
    try:
        value = D(str(metrics[field]))
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("v23 confirmation planning rates are invalid") from exc
    if not value.is_finite() or not D("0") < value <= D("1"):
        raise ValueError("v23 confirmation planning rates are invalid")
    return value


def _confirmation_design(
    manifest: Mapping[str, object], selection: Mapping[str, object]
) -> dict[str, object]:
    """Freeze a capacity design from pre-cutoff independent selection paths."""
    criteria = manifest.get("criteria")
    if not isinstance(criteria, Mapping):
        raise ValueError("v23 confirmation criteria are unavailable")
    if selection.get("schema_version") != 5:
        raise ValueError("v23 selection planning contract is unavailable")
    metrics = selection.get("selection_metrics")
    if not isinstance(metrics, Mapping) or metrics.get(
        "confirmation_capacity_policy"
    ) != "bonferroni_clopper_pearson_lower_bound_v1":
        raise ValueError("v23 selection planning contract is unavailable")
    eligible_rate = _rate(metrics, "eligible_path_rate_lower_bound")
    filled_rate = _rate(metrics, "filled_path_rate_lower_bound")
    range_filled_rate = _rate(
        metrics, "range_filled_path_rate_lower_bound"
    )
    if not (
        criteria.get("criteria_schema_version") == 8
        and criteria.get("confirmation_cohort_policy")
        == "fixed_provider_capacity_paths_v1"
        and criteria.get("fixed_confirmation_paths")
        == V23_FIXED_CONFIRMATION_PATHS
        and criteria.get("dynamic_confirmation_top_up_allowed") is False
        and criteria.get("design_effect_is_capacity_gate") is False
        and criteria.get("provider_capacity_reserve_paths")
        == CONFIRMATION_CAPACITY_RESERVE_PATHS
        and criteria.get("confirmation_block_size") == PATHS_PER_BLOCK
        and criteria.get("incremental_block_evaluation") is True
        and criteria.get("path_admission_policy")
        == "first_context_ready_post_cutoff_paths_v1"
        and _integer(criteria, "maximum_terminal_episodes")
        == V23_FIXED_CONFIRMATION_PATHS
    ):
        raise ValueError("v23 fixed confirmation contract is unavailable")
    if V23_FIXED_CONFIRMATION_PATHS > MAXIMUM_CONTEXT_CANDIDATES:
        raise ValueError("v23 confirmation path capacity reached")
    return {
        "schema_version": 2,
        "policy": "fixed_provider_capacity_paths_v1",
        "eligible_path_rate_lower_bound": format(eligible_rate, "f"),
        "filled_path_rate_lower_bound": format(filled_rate, "f"),
        "range_filled_path_rate_lower_bound": format(range_filled_rate, "f"),
        "required_independent_paths": V23_FIXED_CONFIRMATION_PATHS,
        "design_effect_target_filled_episodes": _integer(
            criteria, "design_effect_required_filled_episodes"
        ),
        "design_effect_is_capacity_gate": False,
        "dynamic_top_up_allowed": False,
        "provider_capacity_reserve_paths": (
            CONFIRMATION_CAPACITY_RESERVE_PATHS
        ),
        "incremental_block_evaluation": True,
        "path_admission_policy": "first_context_ready_post_cutoff_paths_v1",
    }


def _provider_capacity(duration_ms: int) -> dict[str, int]:
    """Return the exact lower-bound capacity inside provider sessions."""
    path_duration_ms = SIGNAL_WARMUP_MS + PATH_ENTRY_WINDOW_MS + TERMINAL_TAIL_MS
    paths_per_session = PROVIDER_CONNECTION_MAX_MS // path_duration_ms
    complete_sessions, remainder_ms = divmod(
        max(0, int(duration_ms)), PROVIDER_CONNECTION_MAX_MS
    )
    maximum_paths = complete_sessions * paths_per_session + min(
        paths_per_session, remainder_ms // path_duration_ms
    )
    return {
        "path_duration_ms": path_duration_ms,
        "provider_session_max_ms": PROVIDER_CONNECTION_MAX_MS,
        "paths_per_provider_session": paths_per_session,
        "maximum_paths_before_deadline": maximum_paths,
    }


def _provider_design_duration(required_paths: int) -> int:
    """Return the minimum wall time after provider packing losses."""
    capacity = _provider_capacity(PROVIDER_CONNECTION_MAX_MS)
    paths_per_session = capacity["paths_per_provider_session"]
    sessions = (required_paths + paths_per_session - 1) // paths_per_session
    remainder = required_paths - (sessions - 1) * paths_per_session
    return (
        (sessions - 1) * PROVIDER_CONNECTION_MAX_MS
        + remainder * capacity["path_duration_ms"]
    )


def _policy(
    manifest: Mapping[str, object], context: Mapping[str, object]
) -> dict[str, object]:
    parameters = manifest["candidate_parameters"]
    rule = parameters.get("entry_veto_rule")
    if not isinstance(rule, Mapping):
        raise ValueError("v23 confirmation veto rule is unavailable")
    if str(parameters.get("regime_policy")) != "range_only":
        raise ValueError("v23 confirmation regime policy is unsupported")
    model = execution_model_contract()
    stop_limit = D(str(parameters["stop_limit_distance"]))
    stop_offset = D(str(parameters["stop_trigger_offset_pct"]))
    return {
        "symbol": "SOLUSDT",
        "entry_gap_bps": str(parameters["entry_gap_bps"]),
        "take_profit_bps": format(D(str(parameters["target_return"])) * D("10000"), "f"),
        "stop_trigger_bps": format((stop_limit - stop_offset) * D("10000"), "f"),
        "stop_limit_bps": format(stop_limit * D("10000"), "f"),
        "notional_quote": str(parameters["evidence_notional_quote"]),
        "entry_ttl_ms": int(parameters["entry_ttl_sec"]) * 1_000,
        "holding_ms": int(parameters["maximum_holding_min"]) * 60_000,
        "cadence_ms": 300_000,
        "latency_ms": int(model["latency_ms"]),
        "cancel_latency_ms": int(rule["cancel_latency_ms"]),
        "stop_grace_ms": int(model["stop_unfilled_grace_ms"]),
        "market_impact_bps": str(model["emergency_market_impact_bps"]),
        "maximum_event_gap_ms": int(model["maximum_event_gap_ms"]),
        "allowed_regimes": ["RANGE"],
        "classifier_fingerprint": str(context["classifier_fingerprint"]),
        "panic_source_fingerprint": str(context["panic_source_fingerprint"]),
        "veto_price_bps": str(rule["prefill_price_change_max_bps"]),
        "veto_signed_flow": str(rule["prefill_signed_trade_flow_max"]),
        "veto_ofi": str(rule["prefill_order_flow_imbalance_max"]),
        "signal_window_ms": int(rule["signal_window_ms"]),
        "maximum_attempts": 10_000,
    }


def plan_v23_confirmation_drafts(
    store,
    archive_directory: Path,
    draft_directory: Path,
    context_db: Path,
    request_directory: Path | None = None,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Freeze and queue each complete post-cutoff block immediately."""
    draft_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    request_directory = request_directory or (
        draft_directory.parent / "confirmation-requests"
    )
    request_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    block_directory = draft_directory.parent / CONFIRMATION_BLOCK_DIRECTORY
    block_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = find_active_v23_manifest(store)
    if manifest is None:
        return {
            "schema_version": 1,
            "mode": "SHADOW_CONFIRMATION",
            "apply_allowed": False,
            "status": "WAITING_V23_SELECTION_ARTIFACT",
            "draft_count": 0,
            "required_independent_paths": None,
            "context_ready_independent_paths": 0,
            "automatic_queueing": True,
            "automatic_confirmation_import": True,
        }
    parameters = manifest["candidate_parameters"]
    selection = load_v23_selection_artifact(store, parameters)
    selection_identity = str(
        parameters["entry_veto_rule"]["selection_artifact_sha256"]
    )
    design = _confirmation_design(manifest, selection)
    required_paths = int(design["required_independent_paths"])
    deadline_ms = int(manifest["confirmation_deadline_ts_ms"])
    cutoff_ms = int(manifest["confirmation_start_ts_ms"])
    maximum_duration_ms = deadline_ms - cutoff_ms
    provider_capacity = _provider_capacity(maximum_duration_ms)
    design_duration_ms = _provider_design_duration(required_paths)
    reachable = (
        required_paths + CONFIRMATION_CAPACITY_RESERVE_PATHS
        <= provider_capacity["maximum_paths_before_deadline"]
    )
    if not reachable:
        return {
            "schema_version": 1,
            "mode": "SHADOW_CONFIRMATION",
            "apply_allowed": False,
            "status": "DESIGN_UNREACHABLE",
            "draft_count": 0,
            "required_independent_paths": required_paths,
            "confirmation_capacity_design": design,
            "design_duration_ms": design_duration_ms,
            "maximum_confirmation_duration_ms": maximum_duration_ms,
            "provider_capacity": provider_capacity,
            "automatic_queueing": True,
            "automatic_confirmation_import": True,
        }
    marker_path = draft_directory.parent / CONFIRMATION_COHORT_MARKER
    marker = {
        "schema_version": 2,
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
        "selection_artifact_sha256": selection_identity,
        "confirmation_start_ts_ms": cutoff_ms,
        "confirmation_deadline_ts_ms": deadline_ms,
        "required_independent_paths": required_paths,
        "confirmation_capacity_design": design,
        "provider_capacity": provider_capacity,
        "block_size": PATHS_PER_BLOCK,
        "maximum_blocks": required_paths // PATHS_PER_BLOCK,
        "admission_policy": "first_context_ready_post_cutoff_paths_v1",
    }
    marker["cohort_sha256"] = fingerprint(marker)
    if marker_path.exists():
        if bounded_json(marker_path) != marker:
            raise ValueError("v23 confirmation cohort contract differs")
    else:
        atomic_json(marker_path, marker)
    chains = _chains(archive_directory, "SOLUSDT")
    paths, progress = context_ready_paths(
        chains,
        context_db,
        started_after_ms=cutoff_ms,
        excluded_source_sha256s=frozenset(
            str(value) for value in selection["source_archive_sha256s"]
        ),
        maximum_ready_paths=required_paths,
        newest_first=False,
    )
    requests: dict[str, dict[str, object]] = {}
    complete_path_count = len(paths) - len(paths) % PATHS_PER_BLOCK
    for block_index in range(0, complete_path_count, PATHS_PER_BLOCK):
        block = paths[block_index : block_index + PATHS_PER_BLOCK]
        contexts = [context for _path, context in block]
        if len({
            (row["classifier_fingerprint"], row["panic_source_fingerprint"])
            for row in contexts
        }) != 1:
            raise ValueError("v23 confirmation context semantics differ")
        request = {
            "request_schema_version": 2,
            "cohort_contract": COHORT_CONTRACT,
            "stability_block_index": (block_index // PATHS_PER_BLOCK) % 4,
            "policy": _policy(manifest, contexts[0]),
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
                for (start, entry_end, end, selected), _context in block
            ],
        }
        requests[fingerprint(request)] = request
    if len(requests) > MAXIMUM_DRAFTS:
        raise ValueError("v23 confirmation draft capacity reached")
    existing_ids = _existing_draft_identities(draft_directory)
    if not existing_ids.issubset(requests):
        raise ValueError("v23 confirmation draft cohort differs")
    created = 0
    previous_block_sha256: str | None = None
    for ordinal, (identity, request) in enumerate(requests.items()):
        block_body = {
            "schema_version": 1,
            "cohort_sha256": marker["cohort_sha256"],
            "block_index": ordinal,
            "request_sha256": identity,
            "source_archive_sha256s": sorted(_request_sources(request)),
            "previous_block_sha256": previous_block_sha256,
        }
        block_path = block_directory / f"{ordinal:02d}-{identity}.json"
        if block_path.exists():
            if bounded_json(block_path) != block_body:
                raise ValueError("v23 confirmation block identity differs")
        else:
            atomic_json(block_path, block_body)
        if identity not in existing_ids:
            atomic_json(draft_directory / f"{identity}.json", request)
            created += 1
        request_path = request_directory / f"{identity}.json"
        if request_path.exists():
            if bounded_json(request_path) != request:
                raise ValueError("v23 confirmation request identity differs")
        else:
            atomic_json(request_path, request)
        previous_block_sha256 = fingerprint(block_body)
    observed_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    remaining_ms = max(0, deadline_ms - observed_now_ms)
    remaining_provider_capacity = _provider_capacity(remaining_ms)
    optimistic_additional_paths = remaining_provider_capacity[
        "maximum_paths_before_deadline"
    ]
    capacity_futile = len(paths) + optimistic_additional_paths < required_paths
    report_directory = draft_directory.parent / "confirmation-reports"
    evaluated_blocks = len([
        path for path in report_directory.glob("*.json")
        if path.name != "status.json"
    ]) if report_directory.is_dir() else 0
    status = (
        "CONFIRMATION_COHORT_COMPLETE"
        if len(paths) == required_paths
        else "READY_TO_REJECT_CAPACITY"
        if capacity_futile
        else "STREAMING_CONFIRMATION_BLOCKS"
        if requests
        else "COLLECTING_POST_CUTOFF_CONTEXT_READY_PATHS"
    )
    return {
        "schema_version": 1,
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
        "status": status,
        "draft_count": len(requests),
        "created_drafts": created,
        "required_independent_paths": required_paths,
        "confirmation_capacity_design": design,
        "complete_independent_paths": len(paths),
        "continuous_sessions": len(chains),
        "frozen_cohort_sha256": marker["cohort_sha256"],
        "queued_block_count": len(requests),
        "evaluated_block_count": evaluated_blocks,
        "remaining_deadline_capacity_paths": optimistic_additional_paths,
        "remaining_provider_capacity": remaining_provider_capacity,
        "capacity_futile": capacity_futile,
        "design_duration_ms": design_duration_ms,
        "provider_capacity": provider_capacity,
        **progress,
        "automatic_queueing": True,
        "automatic_confirmation_import": True,
    }


__all__ = ["plan_v23_confirmation_drafts"]
