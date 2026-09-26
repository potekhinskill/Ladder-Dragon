# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own reviewed experiment CLI responsibilities.
from __future__ import annotations

import json
from pathlib import Path
from ladder_dragon.strategy.prediction.champion_registry import list_champions
from ladder_dragon.strategy.prediction.experiment_lifecycle import confirmation_report, list_experiments, load_manifest
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
from ladder_dragon.strategy.prediction.experiment_parser import _parser
from ladder_dragon.strategy.prediction.experiment_evidence import _entry_veto_inputs
from ladder_dragon.strategy.prediction.experiment_actions import (
    handle_finalize,
    handle_supersede,
    handle_entry_veto_freeze,
    handle_entry_veto_import_history,
    handle_champion_preview,
    handle_champion_activate,
    handle_episode_bootstrap,
    handle_model_validation_import,
    handle_freeze,
)


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
        payload = handle_finalize(args, store)
    elif args.command == "supersede":
        payload = handle_supersede(args, store)
    elif args.command == "entry-veto-report":
        _manifest, payload = _entry_veto_inputs(
            store,
            experiment_id=args.experiment_id,
            cutoff_ts_ms=args.cutoff_ts_ms,
        )
    elif args.command == "entry-veto-freeze":
        payload = handle_entry_veto_freeze(args, store)
    elif args.command == "entry-veto-import-history":
        payload = handle_entry_veto_import_history(args, store)
    elif args.command == "champions":
        payload = list_champions(store, symbol=args.symbol)
    elif args.command == "champion-preview":
        payload = handle_champion_preview(args, store)
    elif args.command == "champion-activate":
        payload = handle_champion_activate(args, store)
    elif args.command == "episode-bootstrap":
        payload = handle_episode_bootstrap(args, store)
    elif args.command == "model-validation-import":
        payload = handle_model_validation_import(args, store)
    else:
        return handle_freeze(args, store)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0
