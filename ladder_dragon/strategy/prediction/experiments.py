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
from ladder_dragon.strategy.prediction.walk_forward import (
    walk_forward_prediction_report,
)


D = Decimal
EDGE_EPSILON_PCT = D("0.000001")
SHADOW_GENERATION = "v10"
EXPERIMENT_HORIZONS_MIN = (90, 120)
MAKER_TTLS = (
    ("ttl60", 3_600),
)
# Version seven retained fills at 35 bps, while versions four and eight had no
# fills at 40 bps. Version ten preserves the version nine market hypothesis and
# starts a new evidence cohort for the hardened confirmation protocol.
MAKER_ENTRY_GAPS = (
    ("gap34", D("0.0034")),
    ("gap36", D("0.0036")),
    ("gap38", D("0.0038")),
)


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

    # Version ten keeps the regime argument for the stable caller contract.
    # Production evidence rejected the RANGE-only cohort, so it cannot gate entry.
    del regime
    variants = []
    for ttl_name, ttl_sec in MAKER_TTLS:
        for gap_name, gap_pct in MAKER_ENTRY_GAPS:
            # An explicit market gap keeps every candidate distinct from the baseline.
            entry_price = market_price * (D("1") - gap_pct)
            variants.append(variant(
                f"v10_maker_{ttl_name}_{gap_name}",
                "maker_entry_gap",
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
) -> tuple[str, ...]:
    """Record every candidate against the same immutable feature snapshot."""
    decision_ids = []
    for variant in variants:
        experiment_id, evidence_role = evidence_assignment(
            store,
            generation=SHADOW_GENERATION,
            symbol=symbol,
            variant=variant,
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            snapshot_ts_ms=features.snapshot_ts_ms,
        )
        candidate_fp, baseline_fp = variant_fingerprints(
            variant,
            generation=SHADOW_GENERATION,
            horizons_min=EXPERIMENT_HORIZONS_MIN,
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
            horizons_min=EXPERIMENT_HORIZONS_MIN,
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
            horizons_min=EXPERIMENT_HORIZONS_MIN,
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
    selection_cohort = selection_experiment_id(SHADOW_GENERATION, symbol)
    for variant in variants:
        samples = store.resolved_samples(
            symbol,
            before_ts_ms=before_ts_ms,
            kind=variant.kind,
            experiment_id=selection_cohort,
            evidence_role="SELECTION",
        )
        walk_forward = walk_forward_prediction_report(
            samples,
            required_horizons_min=EXPERIMENT_HORIZONS_MIN,
        )
        active_samples = [
            row for row in samples if row.outcome.exit_reason != "NO_TRADE"
        ]
        active_gate = walk_forward_prediction_report(
            active_samples,
            required_horizons_min=EXPERIMENT_HORIZONS_MIN,
        )["gate"]
        evidence[variant.variant_id] = (
            variant,
            samples,
            walk_forward,
            active_samples,
            active_gate,
        )
        p_values[variant.variant_id] = configuration_edge_p_value(samples)
    configuration_holm = holm_configuration_correction(p_values)
    reports: dict[str, object] = {}
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
            "outcomes": outcome_counts,
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
                    active_samples
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
    manifests = (
        [
            row for row in list_experiments(store, symbol=symbol)
            if row.get("generation") == SHADOW_GENERATION
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
    return {
        "schema_version": 2,
        "mode": "SHADOW",
        "generation": SHADOW_GENERATION,
        "horizons_min": list(EXPERIMENT_HORIZONS_MIN),
        "baseline": "current_strategy_plan",
        "same_snapshot": True,
        "can_change_orders": False,
        "selection_evidence": {
            "diagnostic_only": True,
            "cannot_confirm_selected_candidate": True,
            "variants": reports,
        },
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
    "record_shadow_variants",
    "shadow_variant_report",
]
