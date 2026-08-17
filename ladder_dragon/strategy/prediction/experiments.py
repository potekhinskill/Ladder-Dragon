# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compare immutable SHADOW strategy variants on identical market windows.
"""Parallel counterfactual experiments with no execution or exchange capability."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from ladder_dragon.strategy.prediction.models import (
    PredictionFeatures,
    TradePlan,
)
from ladder_dragon.strategy.prediction.approval import (
    configuration_edge_p_value,
    holm_configuration_correction,
)
from ladder_dragon.strategy.prediction.confirmation_statistics import (
    DEFAULT_CONFIRMATION_CRITERIA,
    validate_confirmation_criteria,
)
from ladder_dragon.strategy.prediction.experiment_config import (
    SOL_V14_SPEC,
    configured_entry_gap_bps,
    experiment_dimension,
    experiment_spec_for_generation,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    REPORT_SCHEMA_VERSION,
    confirmation_report,
    evidence_assignment,
    list_experiments,
    selection_experiment_id,
    variant_fingerprints,
)
from ladder_dragon.strategy.prediction.runtime import (
    PredictionShadowStore,
    predict_distribution,
)
from ladder_dragon.strategy.prediction.statistical_evidence import (
    resolved_independent_evidence,
)
from ladder_dragon.strategy.prediction.walk_forward import (
    evaluated_walk_forward_samples,
    walk_forward_prediction_report,
)


D = Decimal
EDGE_EPSILON_PCT = D("0.000001")
SHADOW_GENERATION = SOL_V14_SPEC.generation
EXPERIMENT_HORIZONS_MIN = SOL_V14_SPEC.horizons_min
MAKER_TTLS = SOL_V14_SPEC.maker_ttls
MAKER_ENTRY_GAPS = SOL_V14_SPEC.maker_entry_gaps


@dataclass(frozen=True)
class ShadowVariant:
    """One immutable candidate compared with the current strategy plan."""

    variant_id: str
    dimension: str
    kind: str
    plan: TradePlan
    baseline_plan: TradePlan
    maker_only: bool = False
    entry_gap_bps: Decimal | None = None
    regime_policy: str = "always_active"
    model_rule: str = "predict_distribution:v1:expanding_history_before_snapshot"


def _candidate_plan(
    baseline: TradePlan,
    *,
    entry_price: Decimal,
    target_pct: Decimal,
    entry_ttl_sec: int | None = None,
    entry_enabled: bool = True,
    slippage_pct: Decimal | None = None,
) -> TradePlan:
    stop_distance = D("1") - baseline.stop_price / baseline.entry_price
    return TradePlan(
        entry_price=entry_price,
        take_profit_price=entry_price * (D("1") + target_pct),
        stop_price=entry_price * (D("1") - stop_distance),
        notional_quote=baseline.notional_quote,
        fee_pct=baseline.fee_pct,
        slippage_pct=(
            baseline.slippage_pct
            if slippage_pct is None
            else slippage_pct
        ),
        entry_ttl_sec=entry_ttl_sec,
        entry_enabled=entry_enabled,
    )


def build_shadow_variants(
    *,
    market_price: Decimal,
    baseline_plan: TradePlan,
    required_edge_pct: Decimal,
    regime: str,
    generation: str = SHADOW_GENERATION,
    symbol: str | None = None,
) -> tuple[ShadowVariant, ...]:
    """Build narrowed maker candidates above the authoritative fee floor."""
    if not market_price.is_finite() or market_price <= 0:
        raise ValueError("market price must be positive and finite")
    if not required_edge_pct.is_finite() or required_edge_pct <= 0:
        raise ValueError("required edge must be positive and finite")
    baseline_target = (
        baseline_plan.take_profit_price / baseline_plan.entry_price - D("1")
    )
    target_pct = max(baseline_target, required_edge_pct + EDGE_EPSILON_PCT)
    def variant(
        variant_id: str,
        dimension: str,
        *,
        entry_price: Decimal = baseline_plan.entry_price,
        candidate_target: Decimal = target_pct,
        entry_ttl_sec: int | None = None,
        entry_enabled: bool = True,
        maker_only: bool = False,
        entry_gap_pct: Decimal | None = None,
    ) -> ShadowVariant:
        return ShadowVariant(
            variant_id=variant_id,
            dimension=dimension,
            kind=f"EXPERIMENT_{variant_id.upper()}",
            plan=_candidate_plan(
                baseline_plan,
                entry_price=entry_price,
                target_pct=max(candidate_target, target_pct),
                entry_ttl_sec=entry_ttl_sec,
                entry_enabled=entry_enabled,
                slippage_pct=D("0") if maker_only else None,
            ),
            baseline_plan=baseline_plan,
            maker_only=maker_only,
            entry_gap_bps=(
                entry_gap_pct * D("10000")
                if entry_gap_pct is not None else None
            ),
        )

    spec = experiment_spec_for_generation(generation, symbol=symbol)
    # Maker generations keep the regime argument for the stable caller contract.
    # Production evidence rejected the RANGE-only cohort, so it cannot gate entry.
    del regime
    dimension = experiment_dimension(generation, symbol=symbol)
    variants = []
    for ttl_name, ttl_sec in spec.maker_ttls:
        for gap_name, gap_pct in spec.maker_entry_gaps:
            # An explicit market gap keeps every candidate distinct from the baseline.
            entry_price = market_price * (D("1") - gap_pct)
            variants.append(variant(
                f"{spec.generation}_maker_{ttl_name}_{gap_name}",
                dimension,
                entry_price=entry_price,
                entry_ttl_sec=ttl_sec,
                maker_only=True,
                entry_gap_pct=gap_pct,
            ))
    return tuple(variants)


def record_shadow_variants(
    store: PredictionShadowStore,
    *,
    symbol: str,
    features: PredictionFeatures,
    variants: Iterable[ShadowVariant],
    generation: str = SHADOW_GENERATION,
    horizons_min: tuple[int, ...] = EXPERIMENT_HORIZONS_MIN,
) -> tuple[str, ...]:
    """Record every candidate against the same immutable feature snapshot."""
    decision_ids = []
    for variant in variants:
        experiment_id, evidence_role = evidence_assignment(
            store,
            generation=generation,
            symbol=symbol,
            variant=variant,
            horizons_min=horizons_min,
            snapshot_ts_ms=features.snapshot_ts_ms,
        )
        candidate_fp, baseline_fp = variant_fingerprints(
            variant,
            generation=generation,
            horizons_min=horizons_min,
        )
        history = store.resolved_samples(
            symbol,
            before_ts_ms=features.snapshot_ts_ms,
            kind=variant.kind,
        )
        predictions = predict_distribution(
            features,
            variant.plan,
            history,
            horizons_min=horizons_min,
        )
        decision_ids.append(store.record(
            kind=variant.kind,
            symbol=symbol,
            features=features,
            plan=variant.plan,
            baseline_plan=variant.baseline_plan,
            predictions=predictions,
            algorithm_decision=(
                f"variant={variant.variant_id};dimension={variant.dimension}"
            ),
            horizons_min=horizons_min,
            experiment_id=experiment_id,
            evidence_role=evidence_role,
            candidate_fingerprint=candidate_fp,
            baseline_fingerprint=baseline_fp,
        ))
    return tuple(decision_ids)


def shadow_variant_report(
    store: PredictionShadowStore,
    *,
    symbol: str,
    variants: Iterable[ShadowVariant],
    before_ts_ms: int,
    resolved_before_ts_ms: int | None = None,
    generation: str = SHADOW_GENERATION,
    horizons_min: tuple[int, ...] = EXPERIMENT_HORIZONS_MIN,
    superseded_selection_generations: tuple[str, ...] = (),
) -> dict[str, object]:
    """Return independent walk-forward gates; never authorize APPLY."""
    evidence: dict[
        str,
        tuple[
            ShadowVariant,
            list[object],
            dict[str, object],
            list[object],
            dict[str, object],
        ],
    ] = {}
    p_values: dict[str, float] = {}
    selection_cohort = selection_experiment_id(generation, symbol)
    for variant in variants:
        if hasattr(store, "_connect"):
            independent_evidence = resolved_independent_evidence(
                store,
                symbol,
                before_ts_ms=before_ts_ms,
                resolved_before_ts_ms=(
                    before_ts_ms
                    if resolved_before_ts_ms is None
                    else resolved_before_ts_ms
                ),
                kind=variant.kind,
                experiment_id=selection_cohort,
                evidence_role="SELECTION",
                required_horizons_min=horizons_min,
            )
            samples = list(independent_evidence.samples)
        else:
            independent_evidence = None
            samples = store.resolved_samples(
                symbol,
                before_ts_ms=before_ts_ms,
                kind=variant.kind,
                experiment_id=selection_cohort,
                evidence_role="SELECTION",
            )
        walk_forward = walk_forward_prediction_report(
            samples,
            required_horizons_min=horizons_min,
        )
        evaluated_samples = list(evaluated_walk_forward_samples(
            samples, required_horizons_min=horizons_min
        ))
        active_samples = [
            row for row in samples if row.outcome.exit_reason != "NO_TRADE"
        ]
        active_gate = walk_forward_prediction_report(
            active_samples,
            required_horizons_min=horizons_min,
        )["gate"]
        evidence[variant.variant_id] = (
            variant,
            samples,
            walk_forward,
            active_samples,
            active_gate,
        )
        p_values[variant.variant_id] = configuration_edge_p_value(
            evaluated_samples, required_horizons_min=horizons_min
        )
    configuration_holm = holm_configuration_correction(p_values)
    reports: dict[str, object] = {}
    confirmation_design = validate_confirmation_criteria(
        DEFAULT_CONFIRMATION_CRITERIA,
        required_horizons_min=horizons_min,
    )
    for variant_id, (
        variant,
        samples,
        walk_forward,
        active_samples,
        active_gate,
    ) in evidence.items():
        gate = walk_forward["gate"]
        holm_passed = configuration_holm[variant_id]
        outcome_counts = store.outcome_status_counts(
            symbol,
            variant.kind,
            as_of_ms=before_ts_ms,
            experiment_id=selection_cohort,
            evidence_role="SELECTION",
        )
        reports[variant.variant_id] = {
            "dimension": variant.dimension,
            "kind": variant.kind,
            "entry_ttl_sec": variant.plan.entry_ttl_sec,
            "entry_enabled": variant.plan.entry_enabled,
            "entry_order_type": (
                "LIMIT_MAKER" if variant.maker_only else "BASELINE"
            ),
            "exit_order_type": (
                "LIMIT_MAKER" if variant.maker_only else "BASELINE"
            ),
            "target_pct": str(
                variant.plan.take_profit_price / variant.plan.entry_price
                - D("1")
            ),
            "resolved_horizon_samples": len(samples),
            "independent_samples": int(gate.get("independent_samples", 0)),
            "available_independent_samples": int(
                gate.get("available_independent_samples", 0)
            ),
            "training_independent_samples": int(
                gate.get("training_independent_samples", 0)
            ),
            "evaluated_independent_samples": int(
                gate.get("evaluated_independent_samples", 0)
            ),
            "required_total_independent_samples": int(
                gate.get("required_total_independent_samples", 0)
            ),
            "estimated_ready_ts_ms": gate.get("estimated_ready_ts_ms"),
            "outcomes": outcome_counts,
            "statistical_reader": (
                {
                    "scanned_snapshots": independent_evidence.scanned_snapshots,
                    "excluded_overlapping_snapshots": (
                        independent_evidence.excluded_overlapping_snapshots
                    ),
                    "stopped_at_pending_snapshot": (
                        independent_evidence.stopped_at_pending_snapshot
                    ),
                    "bounded_memory": True,
                }
                if independent_evidence is not None
                else {"bounded_memory": True, "test_adapter": True}
            ),
            "entry_gap_bps": (
                str(variant.entry_gap_bps)
                if variant.entry_gap_bps is not None else None
            ),
            "gate": gate,
            "configuration_p_value": p_values[variant_id],
            # Promotion compares a complete strategy replacement. This
            # diagnostic isolates the candidate only where its entry is active.
            "comparison_scope": "full_strategy_replacement",
            "no_trade_opportunity_cost_included": True,
            "active_cohort": {
                "diagnostic_only": True,
                "samples": len(active_samples),
                "net_expectancy_ci": active_gate.get("net_expectancy_ci"),
                "baseline_edge_ci": active_gate.get("baseline_edge_ci"),
                "fill_rate": active_gate.get("fill_rate"),
                "configuration_p_value": configuration_edge_p_value(
                    evaluated_walk_forward_samples(
                        active_samples, required_horizons_min=horizons_min
                    ),
                    required_horizons_min=horizons_min,
                ),
            },
            "configuration_holm_passed": holm_passed,
            # Selection can create a hypothesis, but it cannot confirm one.
            "diagnostic_only": True,
            "cannot_confirm_selected_candidate": True,
            "selection_gate_passed": bool(gate.get("approved")) and holm_passed,
            "promotion_eligible": False,
            "eligible_for_second_gate_review": False,
            "apply_allowed": False,
            "lookahead": False,
        }
    first_counts = next(
        (row["outcomes"] for row in reports.values()), {}
    )
    first_snapshot_ms = int(first_counts.get("first_snapshot_ts_ms") or 0)
    selection_progress = {
        "age_sec": (
            max(0, (int(before_ts_ms) - first_snapshot_ms) // 1_000)
            if first_snapshot_ms else None
        ),
        "snapshots": int(first_counts.get("cohort_snapshots") or 0),
        "resolved_outcomes": sum(
            int(row["outcomes"].get("resolved") or 0)
            for row in reports.values()
        ),
        "total_outcomes": sum(
            int(row["outcomes"].get("total") or 0)
            for row in reports.values()
        ),
    }
    manifests = (
        [
            row for row in list_experiments(store, symbol=symbol)
            if row.get("generation") == generation
        ]
        if hasattr(store, "_connect") else []
    )
    confirmation = (
        confirmation_report(
            store,
            experiment_id=str(manifests[-1]["experiment_id"]),
        )
        if manifests else {
            "schema_version": REPORT_SCHEMA_VERSION,
            "experiment_lifecycle_status": "BLOCKED",
            "confirmation_status": "BLOCKED",
            "blocking_reasons": ["frozen experiment manifest is missing"],
            "first_gate_passed": False,
            "eligible_for_second_gate_review": False,
            "promotion_eligible": False,
            "apply_allowed": False,
            "can_change_orders": False,
            "lookahead": False,
        }
    )
    selection_minimum_duration_ms = max(
        (
            int(row["gate"].get("minimum_calendar_duration_ms", 0))
            for row in reports.values()
        ),
        default=0,
    )
    confirmation_minimum_duration_ms = int(
        confirmation_design["minimum_calendar_duration_ms"]
    )
    return {
        "schema_version": 2,
        "mode": "SHADOW",
        "generation": generation,
        "horizons_min": list(horizons_min),
        "superseded_selection_generations": list(
            superseded_selection_generations
        ),
        "baseline": "current_strategy_plan",
        "same_snapshot": True,
        "calendar_plan": {
            "selection_minimum_duration_ms": selection_minimum_duration_ms,
            "confirmation_minimum_duration_ms": confirmation_minimum_duration_ms,
            "end_to_end_minimum_duration_ms": (
                selection_minimum_duration_ms + confirmation_minimum_duration_ms
            ),
            "embargo_ms": int(DEFAULT_CONFIRMATION_CRITERIA["embargo_ms"]),
            "maximum_practical_duration_ms": 180 * 24 * 60 * 60_000,
        },
        "can_change_orders": False,
        "selection_evidence": {
            "diagnostic_only": True,
            "cannot_confirm_selected_candidate": True,
            "progress": selection_progress,
            "variants": reports,
        },
        "selection_progress": selection_progress,
        "confirmation_evidence": confirmation,
        "diagnostic_evidence": {
            "active_cohorts": True,
            "apply_allowed": False,
        },
        "first_gate_passed": bool(confirmation.get("first_gate_passed")),
        "eligible_for_second_gate_review": bool(
            confirmation.get("eligible_for_second_gate_review")
        ),
        "promotion_eligible": bool(confirmation.get("promotion_eligible")),
        "apply_allowed": False,
        "lookahead": False,
        "variants": reports,
    }


__all__ = [
    "EDGE_EPSILON_PCT",
    "EXPERIMENT_HORIZONS_MIN",
    "MAKER_TTLS",
    "MAKER_ENTRY_GAPS",
    "SHADOW_GENERATION",
    "ShadowVariant",
    "build_shadow_variants",
    "configured_entry_gap_bps",
    "record_shadow_variants",
    "shadow_variant_report",
]
