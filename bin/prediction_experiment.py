# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: control frozen SHADOW experiment hypotheses.
"""Inspect and control selection-to-confirmation experiment state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from product_version import __version__
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    candidate_rule,
    confirmation_report,
    finalize_experiment,
    freeze_experiment,
    list_experiments,
    load_manifest,
    selection_experiment_id,
    supersede_experiment,
    variant_fingerprints,
)
from ladder_dragon.strategy.prediction.experiments import (
    EXPERIMENT_HORIZONS_MIN,
    SHADOW_GENERATION,
    ShadowVariant,
    configured_entry_gap_bps,
)
from ladder_dragon.strategy.prediction.experiment_config import (
    experiment_dimension,
)
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


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
    supersede = subparsers.add_parser(
        "supersede", help="Supersede one experiment without deleting evidence."
    )
    supersede.add_argument("experiment_id")
    supersede.add_argument("--reason", required=True)
    supersede.add_argument("--confirm", required=True)
    return parser


def _source_commit() -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("source commit is unavailable") from exc
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError("source commit is invalid")
    return value


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
    else:
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
                horizons_min=EXPERIMENT_HORIZONS_MIN,
            )
            print(json.dumps({
                "status": "BLOCKED",
                "reason": "review parameters and repeat with --confirm FREEZE",
                "experiment_id": args.experiment_id,
                "candidate": candidate_rule(
                    selected,
                    generation=args.generation,
                    horizons_min=EXPERIMENT_HORIZONS_MIN,
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
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            selection_end_ts_ms=args.selection_end_ts_ms,
            product_version=__version__,
            source_commit=_source_commit(),
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
