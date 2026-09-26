# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce concrete owners and stable thin audit launchers.
"""Source-only contracts for reviewed P2 command migrations."""

import ast
import time

from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES
from ladder_dragon.verification.architecture.harness_ownership import audit_harness_owners, HARNESS_LAUNCHER
from ladder_dragon.verification.architecture.runtime_entry_ownership import audit_runtime_entries, RUNTIME_COMMANDS
from ladder_dragon.verification.architecture.ladder_pct_ownership import audit_ladder_owners
from ladder_dragon.verification.architecture.experiment_ownership import audit_experiment_owners


COMMANDS = {
    "semantic_authorities": ("semantic_authorities", "audit_semantic_authorities"),
    "exchange_boundaries": ("exchange_boundaries", "audit_exchange_boundaries"),
    "guard_contracts": ("guard_contracts", "audit_guard_contracts"),
    "ai_readiness": ("ai_readiness_command", "main"),
    "replay_readiness": ("replay_readiness_command", "main"),
}

NEXT_COMMANDS = {
    "audit_legacy_compatibility": "ladder_dragon.execution.compatibility_command",
    "audit_user_stream_soak": "ladder_dragon.execution.user_stream_soak_command",
    "calibrate_replay": "ladder_dragon.verification.calibration_command",
    "validate_replay_outcomes": "ladder_dragon.verification.replay_outcomes_command",
    "maintenance_state": "ladder_dragon.execution.maintenance_command",
}

OBSERVER_COMMANDS = {
    "record_depth_archive": "ladder_dragon.strategy.depth_record_command",
    "depth_archive_service": "ladder_dragon.strategy.depth_service_command",
    "user_stream_shadow": "ladder_dragon.execution.user_stream_command",
    "market_scenario_shadow": "ladder_dragon.market_analysis.scenario_command",
    "historical_replay_planner": "ladder_dragon.strategy.prediction.replay_planner_command",
}

EVIDENCE_COMMANDS = {
    "migrate_volatility_policy": "ladder_dragon.strategy.volatility_migration_command",
    "volatility_policy": "ladder_dragon.strategy.volatility_selection_command",
    "import_entry_veto_l2": "ladder_dragon.strategy.prediction.entry_veto_import_command",
    "backfill_prediction_archive": "ladder_dragon.strategy.prediction.archive_backfill_command",
    "import_v23_confirmation": "ladder_dragon.strategy.prediction.confirmation_import_command",
}

ADMIN_COMMANDS = {
    "risk_ctl": "ladder_dragon.risk.control_command",
    "review_unattributed_fills": "ladder_dragon.ai.unresolved_review_command",
    "database_retention": "ladder_dragon.persistence.retention_command",
    "check_technical_english": "ladder_dragon.verification.english_command",
    "semgrep_scan": "ladder_dragon.verification.semgrep_command",
}

TOOLING_COMMANDS = {
    "record_bnb_public": "ladder_dragon.strategy.bnb_capture_command",
    "verify_bnb_fills": "ladder_dragon.verification.bnb_fills_command",
    "prediction_history_backfill": "ladder_dragon.strategy.prediction.history_command",
    "update_vwap_env": "ladder_dragon.strategy.vwap_update_command",
    "generate_star_history": "ladder_dragon.verification.star_history_command",
}

ACCOUNTING_COMMANDS = {
    "import_legacy_cost_basis": "ladder_dragon.execution.cost_basis_command",
    "retire_legacy_accounting": "ladder_dragon.execution.retirement_command",
    "revalue_legacy_commissions": "ladder_dragon.execution.commission_command",
    "migrate_indexes": "ladder_dragon.persistence.index_command",
    "backtest": "ladder_dragon.strategy.backtest_command",
}

REPORT_COMMANDS = {
    "pnl_24h": "ladder_dragon.execution.pnl_window_command",
    "pnl_reporter": "ladder_dragon.execution.pnl_report_command",
    "regime_pnl_report": "ladder_dragon.strategy.regime_report_command",
    "production_soak_report": "ladder_dragon.verification.production_soak_command",
    "auto_ladder_map": "ladder_dragon.strategy.ladder_map_command",
}

OPERATIONS_COMMANDS = {
    "ai_advisor_smoke": "ladder_dragon.ai.smoke_command",
    "gen_vwap_env": "ladder_dragon.strategy.vwap_generate_command",
    "depth_archive_retention": "ladder_dragon.strategy.depth_retention_command",
    "mainnet_validation_archive_retention": "ladder_dragon.verification.live.archive_retention_command",
    "ip_guard": "ladder_dragon.execution.ip_guard_command",
}

ENTRY_COMMANDS = {
    "run_dashboard": "ladder_dragon.dashboard.server_command",
    "db_migrate": "ladder_dragon.persistence.migration_command",
    "run_mainnet_validation_batch": "ladder_dragon.verification.live.batch_run_command",
    "replay_historical_entries": "ladder_dragon.strategy.prediction.replay_command",
    "historical_replay_runner": "ladder_dragon.strategy.prediction.replay_runner_command",
}

LIVE_COMMANDS = {
    "binance_testnet_smoke": ("testnet_smoke", "run", "Authenticated Testnet verification command."),
    "binance_mainnet_canary": ("mainnet_canary", "run_canary", "Separately confirmed Mainnet canary command."),
    "mainnet_limit_maker_validation": ("mainnet_limit_maker_validation", "run_validation_drill", "Run the one-shot Mainnet LIMIT_MAKER validation drill."),
    "mainnet_stop_limit_validation": ("mainnet_stop_limit_validation", "run_validation_drill", "CLI compatibility wrapper for STOP_LOSS_LIMIT validation."),
    "mainnet_user_stream_drill": ("mainnet_user_stream_drill", "run_drill", "Run the bounded Mainnet User Data Stream event drill."),
}

OPERATOR_COMMANDS = {
    "ai_plan_runner": ("ladder_dragon.supervision.plan_runner", "parse_args", "AI plan-runner command."),
    "tools_cancel_open": ("ladder_dragon.execution.operator.cancel_open", "parse_args", "Explicit operator cancellation command."),
    "monthly_prediction_report": ("ladder_dragon.strategy.prediction.monthly_report_command", "_load", None),
    "validate_replay_sessions": ("ladder_dragon.verification.replay_sessions", "build_parser", "CLI compatibility wrapper for replay session validation."),
    "mainnet_validation_batch": ("ladder_dragon.verification.live.validation_batch", "create_batch_manifest", "Create a bounded Mainnet validation batch authorization."),
}

CONTRACTS = {
    "ladder_pct_runner": ("ladder_dragon.strategy.ladder_pct_command", "main"),
    "prediction_experiment": ("ladder_dragon.strategy.prediction.experiment_command", "main"),
    **{name: (owner, definition) for name, (owner, definition, _doc) in RUNTIME_COMMANDS.items()},
    "verification_harness": ("ladder_dragon.verification.harness_command", "main"),
    **{name: (owner, definition) for name, (owner, definition, _doc) in OPERATOR_COMMANDS.items()},
    **{name: (f"ladder_dragon.verification.live.{owner}", definition)
       for name, (owner, definition, _doc) in LIVE_COMMANDS.items()},
    "testnet_soak_monitor": ("ladder_dragon.verification.live.soak_command", "main"),
    "audit_execution_authority_paths": ("ladder_dragon.verification.authority_command", "main"),
    "gen_vwap_autotune": ("ladder_dragon.strategy.autotune_command", "main"),
    "daily_trading_digest": ("ladder_dragon.execution.digest_command", "main"),
    **{f"audit_{name}": (f"ladder_dragon.verification.{owner}", definition)
       for name, (owner, definition) in COMMANDS.items()},
    **{name: (owner, "main") for name, owner in NEXT_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in OBSERVER_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in EVIDENCE_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in ADMIN_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in TOOLING_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in ACCOUNTING_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in REPORT_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in OPERATIONS_COMMANDS.items()},
    **{name: (owner, "main") for name, owner in ENTRY_COMMANDS.items()},
    "migrate_indexes": (ACCOUNTING_COMMANDS["migrate_indexes"], "index_statements"),
}


DIGEST_OWNERS = {
    "digest_totals": ("_as_decimal", "_aggregate"),
    "digest_fifo": ("_summaries",),
    "digest_report": ("_money", "_timezone", "_periods", "build_digest"),
    "digest_state": ("_last_sent", "_last_alert", "_mark_state"),
    "digest_command": ("main",),
}
DIGEST_LINKS = {
    "digest_fifo": {"digest_totals": {"ZERO", "PeriodSummary", "_aggregate"}},
    "digest_report": {"digest_fifo": {"_summaries"}, "digest_totals": {"ZERO"}},
    "digest_command": {"digest_report": {"_timezone", "build_digest"},
                       "digest_state": {"_last_sent", "_last_alert", "_mark_state"}},
}


def audit_digest_owners(root):
    violations = []
    for owner, definitions in DIGEST_OWNERS.items():
        source = root / f"ladder_dragon/execution/{owner}.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for name in definitions:
            matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
            minimum = 1 if name == "_timezone" else 2 if name in {"_last_sent", "_last_alert"} else 3
            if len(matches) != 1 or len(matches[0].body) < minimum:
                violations.append(f"{owner}:{name}:concrete_owner_missing")
            elif name == "_timezone" and not isinstance(matches[0].body[0], ast.Try):
                violations.append(f"{owner}:{name}:timezone_boundary_missing")
        for dependency, names in DIGEST_LINKS.get(owner, {}).items():
            imported = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                        and n.module == f"ladder_dragon.execution.{dependency}"
                        for a in n.names if a.asname is None}
            if not names <= imported:
                violations.append(f"{owner}:{dependency}:owner_link_missing")
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"{owner}:reverse_launcher_dependency")
    return violations


AUTOTUNE_OWNERS = {
    "autotune_math": ("adaptive_discount", "decimal_ema"),
    "autotune_history": ("get_stats",),
    "autotune_state": ("load_prev_values", "save_values"),
    "autotune_parser": ("build_parser",),
    "autotune_command": ("main",),
}
AUTOTUNE_LINKS = {
    "autotune_math": {"clamp", "fmt_map", "ema", "adaptive_discount", "decimal_ema"},
    "autotune_history": {"get_stats"},
    "autotune_state": {"load_prev_values", "save_values"},
    "autotune_parser": {"build_parser"},
}


def audit_autotune_owners(root):
    violations = []
    for owner, definitions in AUTOTUNE_OWNERS.items():
        tree = ast.parse((root / f"ladder_dragon/strategy/{owner}.py").read_text(encoding="utf-8"))
        for name in definitions:
            matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
            if len(matches) != 1 or len(matches[0].body) < 3:
                violations.append(f"{owner}:{name}:concrete_owner_missing")
        if owner == "autotune_command":
            for dependency, names in AUTOTUNE_LINKS.items():
                imported = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                            and n.module == f"ladder_dragon.strategy.{dependency}"
                            for a in n.names if a.asname is None}
                if not names <= imported:
                    violations.append(f"{owner}:{dependency}:owner_link_missing")
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"{owner}:reverse_launcher_dependency")
    return violations


AUTHORITY_OWNERS = {
    "authority_contracts": ("AuthorityCallContract", "AuthorityBindingContract"),
    "authority_calls": ("_CallVisitor", "_function_calls"),
    "authority_bindings": ("_BindingVisitor", "_audit_binding_contract"),
    "authority_paths": ("audit_execution_authority_paths",),
    "authority_command": ("main",),
}
AUTHORITY_LINKS = {
    "authority_bindings": {"authority_contracts": {"AuthorityBindingContract"}},
    "authority_paths": {
        "authority_contracts": {"AUTHORITY_CALL_CONTRACTS", "AUTHORITY_BINDING_CONTRACTS"},
        "authority_calls": {"_function_calls"},
        "authority_bindings": {"_audit_binding_contract"},
    },
    "authority_command": {"authority_paths": {"audit_execution_authority_paths"}},
}


def audit_authority_owners(root):
    violations = []
    for owner, definitions in AUTHORITY_OWNERS.items():
        tree = ast.parse((root / f"ladder_dragon/verification/{owner}.py").read_text(encoding="utf-8"))
        for name in definitions:
            matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name]
            if len(matches) != 1 or len(matches[0].body) < 3:
                violations.append(f"{owner}:{name}:concrete_owner_missing")
        if owner == "authority_contracts":
            for name in ("AUTHORITY_CALL_CONTRACTS", "AUTHORITY_BINDING_CONTRACTS"):
                bindings = [n for n in tree.body if isinstance(n, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
                if len(bindings) != 1 or not isinstance(bindings[0].value, ast.Tuple) or not bindings[0].value.elts:
                    violations.append(f"{owner}:{name}:contracts_missing")
        for dependency, names in AUTHORITY_LINKS.get(owner, {}).items():
            imported = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                        and n.module == f"ladder_dragon.verification.{dependency}"
                        for a in n.names if a.asname is None}
            if not names <= imported:
                violations.append(f"{owner}:{dependency}:owner_link_missing")
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"{owner}:reverse_launcher_dependency")
    return violations


SOAK_OWNERS = {
    "soak_policy": ("evaluate_sample", "oco_protection_coverage", "_advance_grace"),
    "soak_sources": ("_read_sources",),
    "soak_reports": ("_atomic_report", "_json_sample", "_finish_report"),
    "soak_parser": ("_parse_monitor_args",),
    "soak_command": ("main",),
}
SOAK_LINKS = {
    "soak_sources": {"soak_policy": {"oco_protection_coverage"}},
    "soak_reports": {"soak_policy": {"SoakSample"}},
    "soak_command": {
        "soak_policy": {"SoakSample", "evaluate_sample", "_advance_grace"},
        "soak_sources": {"_read_sources"},
        "soak_reports": {"_atomic_report", "_json_sample", "_finish_report"},
        "soak_parser": {"_parse_monitor_args"},
    },
}


def audit_soak_owners(root):
    violations = []
    for owner, definitions in SOAK_OWNERS.items():
        tree = ast.parse((root / f"ladder_dragon/verification/live/{owner}.py").read_text(encoding="utf-8"))
        for name in definitions:
            matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
            if len(matches) != 1 or len(matches[0].body) < 3:
                violations.append(f"{owner}:{name}:concrete_owner_missing")
        if owner == "soak_command":
            stops = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_stop"]
            expected = ast.parse("global RUN\nRUN = False").body
            if len(stops) != 1 or ast.dump(ast.Module(body=stops[0].body, type_ignores=[])) != ast.dump(ast.Module(body=expected, type_ignores=[])):
                violations.append(f"{owner}:stop_state_owner_missing")
        for dependency, names in SOAK_LINKS.get(owner, {}).items():
            imported = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                        and n.module == f"ladder_dragon.verification.live.{dependency}"
                        for a in n.names if a.asname is None}
            if not names <= imported:
                violations.append(f"{owner}:{dependency}:owner_link_missing")
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"{owner}:reverse_launcher_dependency")
    return violations


def audit_commands(root):
    violations = (audit_digest_owners(root) + audit_autotune_owners(root)
                  + audit_authority_owners(root) + audit_soak_owners(root) + audit_harness_owners(root)
                  + audit_runtime_entries(root) + audit_ladder_owners(root) + audit_experiment_owners(root))
    for name, (owner, definition) in CONTRACTS.items():
        launcher = root / f"bin/{name}.py"
        source = root / (owner.replace(".", "/") + ".py")
        entry = "cli as main" if name == "ip_guard" else "main"
        expected = ast.parse(f'from {owner} import {entry}\n'
                             'if __name__ == "__main__":\n    raise SystemExit(main())\n')
        if name == "verification_harness":
            expected = ast.parse(HARNESS_LAUNCHER)
        if name == "ladder_pct_runner":
            expected = ast.parse(f'from {owner} import main\nif __name__ == "__main__":\n    main()\n')
        if name in RUNTIME_COMMANDS:
            expected.body.insert(0, ast.Expr(value=ast.Constant(RUNTIME_COMMANDS[name][2])))
            if name == "ai_supervisor":
                expected.body.insert(1, ast.parse("from __future__ import annotations").body[0])
        # Preserve each reviewed launcher's exact documentation, not arbitrary code.
        if name in LIVE_COMMANDS:
            expected.body.insert(0, ast.Expr(value=ast.Constant(LIVE_COMMANDS[name][2])))
        if name in OPERATOR_COMMANDS and OPERATOR_COMMANDS[name][2] is not None:
            expected.body.insert(0, ast.Expr(value=ast.Constant(OPERATOR_COMMANDS[name][2])))
        text = launcher.read_text(encoding="utf-8")
        if len(text.splitlines()) > 20 or ast.dump(ast.parse(text)) != ast.dump(expected):
            violations.append(f"{name}:launcher_ownership")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        if name == "ip_guard":
            wrappers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cli"]
            if len(wrappers) != 1 or len(wrappers[0].body) != 1 or not isinstance(wrappers[0].body[0], ast.Try):
                violations.append(f"{name}:error_boundary_missing")
        for required in {definition, "main"}:
            functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == required]
            # The index command owns its transaction inside one with statement.
            minimum = 2 if name == "migrate_indexes" and required == "main" else 3
            if len(functions) != 1 or len(functions[0].body) < minimum:
                violations.append(f"{name}:concrete_owner_missing")
        # The owner cannot delegate back to executable launcher modules.
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            if any(module == "bin" or module.startswith("bin.") for module in modules):
                violations.append(f"{name}:reverse_launcher_dependency")
    return sorted(set(violations))


def check_command_ownership(context):
    started = time.monotonic()
    try:
        violations = audit_commands(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, UnicodeError, SyntaxError, ValueError):
        violations = ["source_analysis_unavailable"]
        status = Status.BLOCKED
    return CheckResult(name="architecture_command_ownership", status=status, required=True,
                       duration_ms=int((time.monotonic()-started)*1000),
                       summary="Concrete audit owners and thin command launchers",
                       exit_code=EXIT_CODES[status], metrics={"violations": violations})
