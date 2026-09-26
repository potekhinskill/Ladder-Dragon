# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own reviewed experiment CLI responsibilities.
from __future__ import annotations

from decimal import Decimal
import json
from ladder_dragon.strategy.prediction.experiment_lifecycle import load_manifest, selection_experiment_id
from ladder_dragon.strategy.prediction.experiments import ShadowVariant, build_shadow_variants, configured_entry_gap_bps
from ladder_dragon.strategy.prediction.experiment_config import experiment_dimension, experiment_spec_for_generation
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
from ladder_dragon.strategy.prediction.entry_diagnostics import entry_diagnostic_report, latest_entry_veto_selection


def _freeze_horizons(generation: str, symbol: str) -> tuple[int, ...]:
    """Resolve freeze horizons from the exact symbol generation."""
    return experiment_spec_for_generation(
        generation, symbol=symbol
    ).horizons_min


def _entry_veto_inputs(
    store: PredictionShadowStore,
    *,
    experiment_id: str,
    cutoff_ts_ms: int,
) -> tuple[dict[str, object], dict[str, object]]:
    """Resolve one immutable source manifest and its cutoff-safe report."""
    manifest = load_manifest(store, experiment_id)
    parameters = manifest.get("candidate_parameters")
    if not isinstance(parameters, dict):
        raise ValueError("entry-veto source parameters are unavailable")
    report = entry_diagnostic_report(
        store,
        symbol=str(manifest["symbol"]),
        generation=str(manifest["generation"]),
        candidate_fingerprint=str(manifest["candidate_fingerprint"]),
        cutoff_ts_ms=int(cutoff_ts_ms),
        target_return=Decimal(str(parameters["target_return"])),
        candidate_parameters=parameters,
    )
    return manifest, report


def _selection_variants(
    store: PredictionShadowStore,
    *,
    generation: str,
    symbol: str,
    cutoff: int,
) -> tuple[ShadowVariant, ...]:
    cohort = selection_experiment_id(generation, symbol)
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT d.kind,d.plan_json,d.baseline_plan_json
               FROM prediction_decisions d
               JOIN (
                   SELECT kind,MAX(snapshot_ts_ms) AS latest
                   FROM prediction_decisions
                   WHERE experiment_id=? AND evidence_role='SELECTION'
                     AND symbol=? AND snapshot_ts_ms<=?
                   GROUP BY kind
               ) latest ON latest.kind=d.kind
                       AND latest.latest=d.snapshot_ts_ms
               WHERE d.experiment_id=? AND d.evidence_role='SELECTION'
                 AND d.symbol=? ORDER BY d.kind""",
            (cohort, symbol.upper(), cutoff, cohort, symbol.upper()),
        ).fetchall()
    variants = []
    for kind, plan_json, baseline_json in rows:
        plan = store._plan(str(plan_json))
        baseline = store._plan(str(baseline_json))
        if plan is None or baseline is None:
            raise ValueError("selection plan is incomplete")
        normalized_kind = str(kind).upper()
        if not normalized_kind.startswith("EXPERIMENT_"):
            raise ValueError("selection kind is invalid")
        variant_id = normalized_kind.removeprefix("EXPERIMENT_").lower()
        variants.append(ShadowVariant(
            variant_id=variant_id,
            dimension=experiment_dimension(generation, symbol=symbol),
            kind=normalized_kind,
            plan=plan,
            baseline_plan=baseline,
            maker_only=True,
            # The stored price can include exchange tick rounding. The gap is
            # immutable strategy configuration, not snapshot-derived evidence.
            entry_gap_bps=configured_entry_gap_bps(
                variant_id, generation=generation, symbol=symbol
            ),
        ))
    return tuple(variants)


def _preselected_episode_variant(
    store: PredictionShadowStore,
    *,
    generation: str,
    symbol: str,
) -> ShadowVariant:
    """Build the fixed rule from the latest closed, non-secret strategy plan."""
    with store._connect() as connection:
        row = connection.execute(
            """SELECT feature_json,plan_json FROM prediction_decisions
               WHERE symbol=? AND kind='STRATEGY'
               ORDER BY snapshot_ts_ms DESC LIMIT 1""",
            (symbol.upper(),),
        ).fetchone()
    if row is None:
        raise ValueError("a closed strategy plan is required for bootstrap")
    feature = json.loads(str(row[0]))
    baseline = store._plan(str(row[1]))
    if not isinstance(feature, dict) or baseline is None:
        raise ValueError("bootstrap strategy evidence is invalid")
    market = Decimal(str(feature.get("price")))
    entry_veto_rule = None
    target_reachability = None
    spec = experiment_spec_for_generation(generation, symbol=symbol)
    if spec.statistical_design_version == "episode_anytime_expectancy_v8":
        entry_veto_rule, target_reachability = latest_entry_veto_selection(
            store, symbol=symbol
        )
    variants = build_shadow_variants(
        market_price=market,
        baseline_plan=baseline,
        required_edge_pct=Decimal("0.000001"),
        regime=str(feature.get("regime") or "RANGE"),
        generation=generation,
        symbol=symbol,
        entry_veto_rule=entry_veto_rule,
        target_reachability=target_reachability,
    )
    if len(variants) != 1:
        raise ValueError("episode bootstrap requires exactly one candidate")
    return variants[0]
