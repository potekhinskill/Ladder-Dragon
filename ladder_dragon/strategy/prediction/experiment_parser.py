# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own reviewed experiment CLI responsibilities.
from __future__ import annotations

import argparse
import os
from pathlib import Path
from ladder_dragon.strategy.prediction.experiments import SHADOW_GENERATION


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
    historical_veto = subparsers.add_parser(
        "entry-veto-import-history",
        help="Import immutable historical replay selection blocks.",
    )
    historical_veto.add_argument("experiment_id")
    historical_veto.add_argument("--cutoff-ts-ms", required=True, type=int)
    historical_veto.add_argument(
        "--report", required=True, type=Path, action="append"
    )
    historical_veto.add_argument(
        "--report-sha256", required=True, action="append"
    )
    historical_veto.add_argument("--confirm", required=True)
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
