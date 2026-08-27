# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: control frozen SHADOW experiment hypotheses.
"""Inspect and control selection-to-confirmation experiment state."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess

from product_version import __version__
from ladder_dragon.risk.risk_manager import (
    RiskLimits,
    confirmed_execution_halt,
)
from ladder_dragon.strategy.prediction.champion_registry import (
    activate_champion,
    active_champion,
    execution_policy_from_manifest,
    list_champions,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    candidate_rule,
    confirmation_report,
    finalize_experiment,
    freeze_experiment,
    freeze_preselected_episode_experiment,
    list_experiments,
    load_manifest,
    selection_experiment_id,
    sha256_json,
    supersede_experiment,
    variant_fingerprints,
)
from ladder_dragon.strategy.prediction.experiments import (
    SHADOW_GENERATION,
    ShadowVariant,
    build_shadow_variants,
    configured_entry_gap_bps,
)
from ladder_dragon.strategy.prediction.experiment_config import (
    experiment_dimension,
    experiment_spec_for_generation,
    experiment_spec_for_symbol,
)
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
from ladder_dragon.strategy.prediction.episode_evidence import (
    record_model_validation,
)
from ladder_dragon.strategy.prediction.entry_diagnostics import (
    entry_diagnostic_report,
    freeze_entry_veto_selection,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Control immutable SHADOW experiment hypotheses."
    )
    parser.add_argument(
        "--database",
        default=os.getenv("PREDICTION_SHADOW_DB", "db/prediction_shadow.sqlite3"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="List experiment state.")
    status.add_argument("--symbol")
    show = subparsers.add_parser("show", help="Show one immutable manifest.")
    show.add_argument("experiment_id")
    report = subparsers.add_parser("report", help="Evaluate confirmation evidence.")
    report.add_argument("experiment_id")
    finalize = subparsers.add_parser(
        "finalize", help="Finalize one reviewed confirmation report."
    )
    finalize.add_argument("experiment_id")
    finalize.add_argument("--report-sha256", required=True)
    finalize.add_argument("--confirm", required=True)
    freeze = subparsers.add_parser("freeze", help="Freeze one selected candidate.")
    freeze.add_argument("--experiment-id", required=True)
    freeze.add_argument("--symbol", required=True)
    freeze.add_argument("--variant-id", required=True)
    freeze.add_argument("--selection-end-ts-ms", required=True, type=int)
    freeze.add_argument("--generation", default=SHADOW_GENERATION)
    freeze.add_argument("--confirm", default="")
    bootstrap = subparsers.add_parser(
        "episode-bootstrap",
        help="Freeze the preregistered single candidate before live episodes.",
    )
    bootstrap.add_argument("--experiment-id", required=True)
    bootstrap.add_argument("--symbol", default="SOLUSDT")
    bootstrap.add_argument("--generation")
    bootstrap.add_argument("--confirm", default="")
    validation = subparsers.add_parser(
        "model-validation-import",
        help="Import a reviewed sanitized execution replay validation.",
    )
    validation.add_argument("--symbol", default="SOLUSDT")
    validation.add_argument("--generation")
    validation.add_argument("--experiment-id", required=True)
    validation.add_argument("--report", required=True, type=Path)
    validation.add_argument("--report-sha256", required=True)
    validation.add_argument("--confirm", default="")
    supersede = subparsers.add_parser(
        "supersede", help="Supersede one experiment without deleting evidence."
    )
    supersede.add_argument("experiment_id")
    supersede.add_argument("--reason", required=True)
    supersede.add_argument("--confirm", required=True)
    veto_report = subparsers.add_parser(
        "entry-veto-report",
        help="Report cutoff-safe L2 entry-veto selection evidence.",
    )
    veto_report.add_argument("experiment_id")
    veto_report.add_argument("--cutoff-ts-ms", required=True, type=int)
    veto_freeze = subparsers.add_parser(
        "entry-veto-freeze",
        help="Freeze one reviewed future entry-veto selection artifact.",
    )
    veto_freeze.add_argument("experiment_id")
    veto_freeze.add_argument("--cutoff-ts-ms", required=True, type=int)
    veto_freeze.add_argument("--confirm", required=True)
    champions = subparsers.add_parser(
        "champions", help="List immutable CHAMPION activations."
    )
    champions.add_argument("--symbol")
    preview_champion = subparsers.add_parser(
        "champion-preview", help="Preview one exact CHAMPION activation."
    )
    preview_champion.add_argument("experiment_id")
    preview_champion.add_argument("--maximum-order-usdt", required=True)
    preview_champion.add_argument("--maximum-inventory-usdt", required=True)
    activate = subparsers.add_parser(
        "champion-activate", help="Activate one reviewed CONFIRMED candidate."
    )
    activate.add_argument("experiment_id")
    activate.add_argument("--report-sha256", required=True)
    activate.add_argument("--manifest-sha256", required=True)
    activate.add_argument(
        "--expected-execution-policy-fingerprint", required=True
    )
    activate.add_argument("--expected-previous-activation-id", required=True)
    activate.add_argument("--maximum-order-usdt", required=True)
    activate.add_argument("--maximum-inventory-usdt", required=True)
    activate.add_argument("--confirm", required=True)
    return parser


def _source_commit() -> str:
    """Return one clean, published, annotated release checkout identity."""
    def git_output(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    try:
        value = git_output("rev-parse", "HEAD").lower()
        if git_output("status", "--porcelain"):
            raise RuntimeError("CHAMPION activation requires a clean checkout")
        tag = f"v{__version__}"
        if git_output("cat-file", "-t", f"refs/tags/{tag}") != "tag":
            raise RuntimeError("CHAMPION activation requires an annotated release tag")
        if git_output("rev-list", "-n", "1", tag).lower() != value:
            raise RuntimeError("CHAMPION activation release tag differs from HEAD")
        if git_output("rev-parse", "origin/main").lower() != value:
            raise RuntimeError("CHAMPION activation requires the published main release")
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("source commit is unavailable") from exc
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError("source commit is invalid")
    return value


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
    variants = build_shadow_variants(
        market_price=market,
        baseline_plan=baseline,
        required_edge_pct=Decimal("0.000001"),
        regime=str(feature.get("regime") or "RANGE"),
        generation=generation,
        symbol=symbol,
    )
    if len(variants) != 1:
        raise ValueError("episode bootstrap requires exactly one candidate")
    return variants[0]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = PredictionShadowStore(Path(args.database))
    if args.command == "status":
        payload = list_experiments(store, symbol=args.symbol)
    elif args.command == "show":
        payload = load_manifest(store, args.experiment_id)
    elif args.command == "report":
        payload = confirmation_report(store, experiment_id=args.experiment_id)
    elif args.command == "finalize":
        if args.confirm != "FINALIZE":
            raise SystemExit("--confirm must equal FINALIZE")
        payload = finalize_experiment(
            store,
            experiment_id=args.experiment_id,
            expected_report_sha256=args.report_sha256,
        )
    elif args.command == "supersede":
        if args.confirm != "SUPERSEDE":
            raise SystemExit("--confirm must equal SUPERSEDE")
        payload = {
            "experiment_id": args.experiment_id,
            "status": supersede_experiment(
                store,
                experiment_id=args.experiment_id,
                reason=args.reason,
            ),
        }
    elif args.command == "entry-veto-report":
        _manifest, payload = _entry_veto_inputs(
            store,
            experiment_id=args.experiment_id,
            cutoff_ts_ms=args.cutoff_ts_ms,
        )
    elif args.command == "entry-veto-freeze":
        if args.confirm != "FREEZE-VETO":
            raise SystemExit("--confirm must equal FREEZE-VETO")
        manifest, _report = _entry_veto_inputs(
            store,
            experiment_id=args.experiment_id,
            cutoff_ts_ms=args.cutoff_ts_ms,
        )
        parameters = manifest["candidate_parameters"]
        payload = freeze_entry_veto_selection(
            store,
            symbol=str(manifest["symbol"]),
            generation=str(manifest["generation"]),
            candidate_fingerprint=str(manifest["candidate_fingerprint"]),
            cutoff_ts_ms=args.cutoff_ts_ms,
            target_return=Decimal(str(parameters["target_return"])),
            candidate_parameters=parameters,
        )
    elif args.command == "champions":
        payload = list_champions(store, symbol=args.symbol)
    elif args.command == "champion-preview":
        manifest = load_manifest(store, args.experiment_id)
        report = confirmation_report(store, experiment_id=args.experiment_id)
        current = active_champion(store, symbol=str(manifest["symbol"]))
        policy = None
        policy_error = None
        try:
            policy = execution_policy_from_manifest(
                manifest,
                confirmation=report,
                maximum_order_notional_usdt=args.maximum_order_usdt,
                maximum_inventory_usdt=args.maximum_inventory_usdt,
            )
        except ValueError as exc:
            if report.get("promotion_eligible"):
                raise
            policy_error = str(exc)
        payload = {
            "status": "READY_FOR_EXPLICIT_ACTIVATION"
            if report.get("promotion_eligible") else "BLOCKED",
            "experiment_id": args.experiment_id,
            "symbol": manifest["symbol"],
            "manifest_sha256": manifest["manifest_sha256"],
            "confirmation_report_sha256": report.get("report_sha256"),
            "promotion_eligible": bool(report.get("promotion_eligible")),
            "current_champion_activation_id": (
                current["activation_id"] if current is not None else None
            ),
            "execution_policy": policy,
            "execution_policy_fingerprint": (
                sha256_json(policy) if policy is not None else None
            ),
            "apply_allowed": False,
            "reason": (
                "repeat with champion-activate and --confirm ACTIVATE"
                if report.get("promotion_eligible")
                else policy_error or "execution model is not promotion-ready"
                if report.get("evaluation_passed")
                and report.get("execution_model_gate", {}).get("status")
                == "NOT_IMPLEMENTED"
                else "independent confirmation has not passed"
            ),
        }
    elif args.command == "champion-activate":
        if args.confirm != "ACTIVATE":
            raise SystemExit("--confirm must equal ACTIVATE")
        previous = args.expected_previous_activation_id.strip()
        if previous.upper() == "NONE":
            previous = None
        limits = RiskLimits.from_env()
        # Keep reset excluded until the immutable activation row is committed.
        with confirmed_execution_halt(limits):
            payload = activate_champion(
                store,
                experiment_id=args.experiment_id,
                expected_report_sha256=args.report_sha256,
                expected_manifest_sha256=args.manifest_sha256,
                expected_execution_policy_fingerprint=(
                    args.expected_execution_policy_fingerprint
                ),
                expected_previous_activation_id=previous,
                maximum_order_notional_usdt=args.maximum_order_usdt,
                maximum_inventory_usdt=args.maximum_inventory_usdt,
                product_version=__version__,
                source_commit=_source_commit(),
                execution_halt_confirmed=True,
            )
    elif args.command == "episode-bootstrap":
        if args.confirm != "BOOTSTRAP":
            raise SystemExit("--confirm must equal BOOTSTRAP")
        generation = (
            args.generation
            or experiment_spec_for_symbol(args.symbol).generation
        )
        spec = experiment_spec_for_generation(
            generation, symbol=args.symbol
        )
        selected = _preselected_episode_variant(
            store,
            generation=generation,
            symbol=args.symbol,
        )
        payload = freeze_preselected_episode_experiment(
            store,
            experiment_id=args.experiment_id,
            generation=generation,
            symbol=args.symbol,
            selected_variant=selected,
            horizons_min=spec.horizons_min,
            product_version=__version__,
            source_commit=_source_commit(),
        )
    elif args.command == "model-validation-import":
        if args.confirm != "IMPORT":
            raise SystemExit("--confirm must equal IMPORT")
        if args.report.stat().st_size > 65_536:
            raise ValueError("replay validation report is too large")
        report_payload = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report_payload, dict):
            raise ValueError("replay validation report must be an object")
        report_sha = sha256_json(report_payload)
        if report_sha != args.report_sha256.strip().lower():
            raise ValueError("replay validation report fingerprint differs")
        generation = (
            args.generation
            or experiment_spec_for_symbol(args.symbol).generation
        )
        spec = experiment_spec_for_generation(
            generation, symbol=args.symbol
        )
        if spec.lifecycle_mode != "PROMOTION":
            raise ValueError("model validation requires a promotion generation")
        payload = {
            "validation_id": record_model_validation(
                store,
                symbol=args.symbol,
                execution_model_rule=spec.execution_model_rule,
                experiment_id=args.experiment_id,
                report=report_payload,
            ),
            "report_sha256": report_sha,
            "apply_allowed": False,
        }
    else:
        generation_spec = experiment_spec_for_generation(
            args.generation, symbol=args.symbol
        )
        if generation_spec.lifecycle_mode != "PROMOTION":
            raise SystemExit(
                "diagnostic-only generations cannot enter confirmation"
            )
        if generation_spec.statistical_design_version == "episode_alpha_spending_v1":
            raise SystemExit(
                "promotion episodes must use the episode-bootstrap command"
            )
        horizons_min = _freeze_horizons(args.generation, args.symbol)
        variants = _selection_variants(
            store,
            generation=args.generation,
            symbol=args.symbol,
            cutoff=args.selection_end_ts_ms,
        )
        selected = next(
            (row for row in variants if row.variant_id == args.variant_id), None
        )
        if selected is None:
            raise SystemExit("selected variant is absent from the selection cohort")
        if args.confirm != "FREEZE":
            candidate_fp, baseline_fp = variant_fingerprints(
                selected,
                generation=args.generation,
                horizons_min=horizons_min,
            )
            print(json.dumps({
                "status": "BLOCKED",
                "reason": "review parameters and repeat with --confirm FREEZE",
                "experiment_id": args.experiment_id,
                "candidate": candidate_rule(
                    selected,
                    generation=args.generation,
                    horizons_min=horizons_min,
                ),
                "candidate_fingerprint": candidate_fp,
                "baseline_fingerprint": baseline_fp,
                "selection_end_ts_ms": args.selection_end_ts_ms,
                "apply_allowed": False,
            }, indent=2, sort_keys=True))
            return 2
        payload = freeze_experiment(
            store,
            experiment_id=args.experiment_id,
            generation=args.generation,
            symbol=args.symbol,
            selected_variant=selected,
            all_variants=variants,
            horizons_min=horizons_min,
            selection_end_ts_ms=args.selection_end_ts_ms,
            product_version=__version__,
            source_commit=_source_commit(),
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
