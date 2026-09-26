# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own reviewed experiment CLI responsibilities.
from __future__ import annotations

from decimal import Decimal
import json
from product_version import __version__
from ladder_dragon.risk.risk_manager import RiskLimits, confirmed_execution_halt
from ladder_dragon.strategy.prediction.champion_registry import activate_champion, active_champion, execution_policy_from_manifest
from ladder_dragon.strategy.prediction.experiment_lifecycle import candidate_rule, confirmation_report, finalize_experiment, freeze_experiment, freeze_preselected_episode_experiment, load_manifest, sha256_json, supersede_experiment, variant_fingerprints
from ladder_dragon.strategy.prediction.experiment_config import experiment_spec_for_generation, experiment_spec_for_symbol
from ladder_dragon.strategy.prediction.episode_evidence import record_model_validation
from ladder_dragon.strategy.prediction.entry_diagnostics import freeze_entry_veto_selection
from ladder_dragon.strategy.prediction.historical_selection import import_historical_selection
from ladder_dragon.strategy.prediction.experiment_provenance import _source_commit
from ladder_dragon.strategy.prediction.experiment_evidence import _freeze_horizons, _entry_veto_inputs, _selection_variants, _preselected_episode_variant


def handle_finalize(args, store):
    if args.confirm != "FINALIZE":
        raise SystemExit("--confirm must equal FINALIZE")
    payload = finalize_experiment(
        store,
        experiment_id=args.experiment_id,
        expected_report_sha256=args.report_sha256,
    )

    return payload


def handle_supersede(args, store):
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

    return payload


def handle_entry_veto_freeze(args, store):
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

    return payload


def handle_entry_veto_import_history(args, store):
    if args.confirm != "IMPORT-HISTORICAL-VETO":
        raise SystemExit(
            "--confirm must equal IMPORT-HISTORICAL-VETO"
        )
    if len(args.report) != len(args.report_sha256):
        raise ValueError("historical report identities are incomplete")
    manifest = load_manifest(store, args.experiment_id)
    payload = import_historical_selection(
        store,
        report_files=list(zip(args.report, args.report_sha256)),
        source_generation=str(manifest["generation"]),
        candidate_fingerprint=str(manifest["candidate_fingerprint"]),
        cutoff_ts_ms=args.cutoff_ts_ms,
    )

    return payload


def handle_champion_preview(args, store):
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

    return payload


def handle_champion_activate(args, store):
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

    return payload


def handle_episode_bootstrap(args, store):
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

    return payload


def handle_model_validation_import(args, store):
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

    return payload


def handle_freeze(args, store):
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
