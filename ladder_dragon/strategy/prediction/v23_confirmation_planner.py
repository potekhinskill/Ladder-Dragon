# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze post-selection L2 paths for v23 confirmation review.
"""Plan a disjoint confirmation cohort from one immutable v23 manifest."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Mapping

from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json
from ladder_dragon.strategy.prediction.episode_semantics import (
    execution_model_contract,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_replay_planner import (
    COHORT_CONTRACT,
    MAXIMUM_CONTEXT_CANDIDATES,
    MAXIMUM_DRAFTS,
    PATHS_PER_BLOCK,
    SIGNAL_WARMUP_MS,
    PATH_ENTRY_WINDOW_MS,
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


def _paths_for(required: int, rate: Decimal) -> int:
    return int((D(required) / rate).to_integral_value(rounding=ROUND_CEILING))


def _confirmation_design(
    manifest: Mapping[str, object], selection: Mapping[str, object]
) -> dict[str, object]:
    """Freeze a capacity design from pre-cutoff independent selection paths."""
    criteria = manifest.get("criteria")
    if not isinstance(criteria, Mapping):
        raise ValueError("v23 confirmation criteria are unavailable")
    if selection.get("schema_version") != 4:
        raise ValueError("v23 selection planning contract is unavailable")
    metrics = selection.get("selection_metrics")
    if not isinstance(metrics, Mapping) or metrics.get(
        "confirmation_capacity_policy"
    ) != "leave_one_independent_path_out_lower_bound_v1":
        raise ValueError("v23 selection planning contract is unavailable")
    eligible_rate = _rate(metrics, "eligible_path_rate_lower_bound")
    filled_rate = _rate(metrics, "filled_path_rate_lower_bound")
    range_filled_rate = _rate(
        metrics, "range_filled_path_rate_lower_bound"
    )
    required = max(
        _paths_for(
            _integer(criteria, "minimum_eligible_terminal_episodes"),
            eligible_rate,
        ),
        _paths_for(
            max(
                _integer(criteria, "minimum_filled_episodes"),
                _integer(criteria, "design_effect_required_filled_episodes"),
            ),
            filled_rate,
        ),
        _paths_for(
            _integer(criteria, "minimum_regime_filled_episodes"),
            range_filled_rate,
        ),
    )
    grouped = ((required + PATHS_PER_BLOCK - 1) // PATHS_PER_BLOCK) * PATHS_PER_BLOCK
    if grouped > MAXIMUM_CONTEXT_CANDIDATES:
        raise ValueError("v23 confirmation path capacity reached")
    return {
        "schema_version": 1,
        "policy": "pre_cutoff_rate_lower_bounds_with_fixed_attrition_v1",
        "eligible_path_rate_lower_bound": format(eligible_rate, "f"),
        "filled_path_rate_lower_bound": format(filled_rate, "f"),
        "range_filled_path_rate_lower_bound": format(range_filled_rate, "f"),
        "required_independent_paths": grouped,
        "dynamic_top_up_allowed": False,
    }


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
) -> dict[str, object]:
    """Freeze new post-cutoff paths; never queue or import them automatically."""
    draft_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
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
            "automatic_queueing": False,
            "automatic_confirmation_import": False,
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
    design_duration_ms = required_paths * (
        SIGNAL_WARMUP_MS + PATH_ENTRY_WINDOW_MS + TERMINAL_TAIL_MS
    )
    reachable = design_duration_ms <= deadline_ms - cutoff_ms
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
            "maximum_confirmation_duration_ms": deadline_ms - cutoff_ms,
            "automatic_queueing": False,
            "automatic_confirmation_import": False,
        }
    chains = _chains(archive_directory, "SOLUSDT")
    paths, progress = context_ready_paths(
        chains,
        context_db,
        started_after_ms=cutoff_ms,
        excluded_source_sha256s=frozenset(
            str(value) for value in selection["source_archive_sha256s"]
        ),
        maximum_ready_paths=required_paths,
    )
    if len(paths) < required_paths:
        return {
            "schema_version": 1,
            "mode": "SHADOW_CONFIRMATION",
            "apply_allowed": False,
            "status": "COLLECTING_POST_CUTOFF_CONTEXT_READY_PATHS",
            "draft_count": 0,
            "required_independent_paths": required_paths,
            "confirmation_capacity_design": design,
            "complete_independent_paths": len(paths),
            "continuous_sessions": len(chains),
            "design_duration_ms": design_duration_ms,
            **progress,
            "automatic_queueing": False,
            "automatic_confirmation_import": False,
        }
    requests: dict[str, dict[str, object]] = {}
    for block_index in range(0, required_paths, PATHS_PER_BLOCK):
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
    marker_path = draft_directory.parent / CONFIRMATION_COHORT_MARKER
    marker = {
        "schema_version": 1,
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
        "selection_artifact_sha256": selection_identity,
        "confirmation_start_ts_ms": cutoff_ms,
        "request_sha256s": sorted(requests),
        "source_archive_sha256s": sorted({
            source
            for request in requests.values()
            for source in _request_sources(request)
        }),
        "required_independent_paths": required_paths,
        "confirmation_capacity_design": design,
    }
    marker["cohort_sha256"] = fingerprint(marker)
    existing_ids = _existing_draft_identities(draft_directory)
    if marker_path.exists():
        frozen = bounded_json(marker_path)
        status = (
            "CONFIRMATION_COHORT_FROZEN_FOR_REVIEW"
            if frozen != marker or existing_ids.issubset(requests)
            else "CONFIRMATION_COHORT_REVIEW_REQUIRED"
        )
        return {
            "schema_version": 1,
            "mode": "SHADOW_CONFIRMATION",
            "apply_allowed": False,
            "status": status,
            "draft_count": len(existing_ids),
            "created_drafts": 0,
            "required_independent_paths": required_paths,
            "confirmation_capacity_design": design,
            "complete_independent_paths": len(paths),
            "frozen_cohort_sha256": frozen.get("cohort_sha256"),
            **progress,
            "automatic_queueing": False,
            "automatic_confirmation_import": False,
        }
    if not existing_ids.issubset(requests):
        raise ValueError("v23 confirmation draft cohort differs")
    created = 0
    for identity, request in requests.items():
        if identity not in existing_ids:
            atomic_json(draft_directory / f"{identity}.json", request)
            created += 1
    atomic_json(marker_path, marker)
    return {
        "schema_version": 1,
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
        "status": "CONFIRMATION_DRAFTS_READY_FOR_OPERATOR_REVIEW",
        "draft_count": len(requests),
        "created_drafts": created,
        "required_independent_paths": required_paths,
        "confirmation_capacity_design": design,
        "complete_independent_paths": len(paths),
        "continuous_sessions": len(chains),
        "frozen_cohort_sha256": marker["cohort_sha256"],
        "design_duration_ms": design_duration_ms,
        **progress,
        "automatic_queueing": False,
        "automatic_confirmation_import": False,
    }


__all__ = ["plan_v23_confirmation_drafts"]
