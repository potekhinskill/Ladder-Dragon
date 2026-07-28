import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _line_count(path: str) -> int:
    return len((ROOT / path).read_text(encoding="utf-8").splitlines())


def test_cli_launchers_remain_thin_and_never_alias_module_identity():
    for relative in (
        "bin/ai_plan_runner.py",
        "bin/db_migrate.py",
        "bin/ai_supervisor.py",
        "bin/autosize_universal.py",
        "bin/binance_testnet_smoke.py",
        "bin/binance_mainnet_canary.py",
        "bin/tools_cancel_open.py",
    ):
        assert _line_count(relative) <= 20
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        assert "sys.modules" not in (ROOT / relative).read_text(
            encoding="utf-8"
        )
        imported_roots = {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert imported_roots <= {"__future__", "ladder_dragon"}


def test_application_package_never_depends_on_bin_entrypoints():
    violations = []
    for path in (ROOT / "ladder_dragon").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "bin"
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "bin" or alias.name.startswith("bin."):
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}"
                        )
    assert violations == []


def test_known_runtime_monoliths_can_only_shrink():
    """Prevent feature work from enlarging legacy orchestration modules."""
    budgets = {
        "ladder_dragon/supervision/runtime.py": 4824,
        "ladder_dragon/execution/worker/runtime.py": 1661,
        "ladder_dragon/execution/worker/bootstrap.py": 18,
        "ladder_dragon/execution/worker/lifecycle.py": 577,
        "ladder_dragon/execution/worker/event_loop.py": 412,
        "ladder_dragon/dashboard/runtime.py": 2867,
        "ladder_dragon/execution/order_recovery.py": 1284,
        "ladder_dragon/strategy/prediction/runtime.py": 1300,
        "ladder_dragon/ai/context/runtime.py": 1684,
        "ladder_dragon/execution/orders/runtime.py": 1335,
        "ladder_dragon/execution/protection/runtime.py": 1095,
    }
    oversized = {
        path: (_line_count(path), budget)
        for path, budget in budgets.items()
        if _line_count(path) > budget
    }
    assert oversized == {}


def test_supervisor_policies_live_in_the_application_package():
    source = (
        ROOT / "ladder_dragon/supervision/runtime.py"
    ).read_text(encoding="utf-8")
    assert "from ladder_dragon.supervision.config import" in source
    assert "from ladder_dragon.supervision.entry_policy import" in source
    assert "from ladder_dragon.supervision.vwap_config import" in source
    assert (ROOT / "ladder_dragon/supervision/plan_runner.py").is_file()


def test_supervisor_risk_recovery_and_process_services_are_physical():
    """Keep extracted orchestration out of the compatibility runtime."""
    runtime = ast.parse(
        (ROOT / "ladder_dragon/supervision/runtime.py").read_text(
            encoding="utf-8"
        )
    )
    wrappers = {
        node.name: node
        for node in runtime.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"_build_risk_snapshot", "_pre_running_recovery_gate"}
    }
    assert set(wrappers) == {
        "_build_risk_snapshot",
        "_pre_running_recovery_gate",
    }
    assert all(len(node.body) <= 2 for node in wrappers.values())

    services = {
        "ladder_dragon/supervision/risk_cycle.py": "build_risk_snapshot",
        "ladder_dragon/supervision/recovery_gate.py": (
            "pre_running_recovery_gate"
        ),
        "ladder_dragon/supervision/process_manager.py": "stop_child",
    }
    for relative, function_name in services.items():
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        assert any(
            isinstance(node, ast.FunctionDef) and node.name == function_name
            for node in tree.body
        )


def test_worker_buy_service_has_no_legacy_runtime_wrapper():
    runtime = ast.parse(
        (ROOT / "ladder_dragon/execution/worker/runtime.py").read_text(
            encoding="utf-8"
        )
    )
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "maybe_place_buys"
        for node in runtime.body
    )
    service = ast.parse(
        (ROOT / "ladder_dragon/execution/worker/buy_service.py").read_text(
            encoding="utf-8"
        )
    )
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "place_buys"
        for node in service.body
    )


def test_worker_stats_service_has_no_legacy_runtime_wrapper():
    runtime = ast.parse(
        (ROOT / "ladder_dragon/execution/worker/runtime.py").read_text(
            encoding="utf-8"
        )
    )
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_stats_poll_mytrades_once"
        for node in runtime.body
    )
    service = ast.parse(
        (ROOT / "ladder_dragon/execution/worker/stats_sync.py").read_text(
            encoding="utf-8"
        )
    )
    assert any(
        isinstance(node, ast.FunctionDef)
        and node.name == "sync_account_trades"
        for node in service.body
    )


def test_worker_main_uses_explicit_mutable_runtime_state():
    runtime = ast.parse(
        (ROOT / "ladder_dragon/execution/worker/runtime.py").read_text(
            encoding="utf-8"
        )
    )
    bootstrap = ast.parse(
        (ROOT / "ladder_dragon/execution/worker/bootstrap.py").read_text(
            encoding="utf-8"
        )
    )
    lifecycle = ast.parse(
        (ROOT / "ladder_dragon/execution/worker/lifecycle.py").read_text(
            encoding="utf-8"
        )
    )
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "main"
        for node in runtime.body
    )
    lifecycle_names = {
        node.name
        for node in lifecycle.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    assert {
        "WorkerRuntimeState",
        "run_worker",
    } <= lifecycle_names
    assert {
        node.name
        for node in bootstrap.body
        if isinstance(node, ast.FunctionDef)
    } == {"main"}


def test_decomposition_targets_have_explicit_package_boundaries():
    required = (
        "ladder_dragon/supervision/risk_cycle.py",
        "ladder_dragon/supervision/symbol_service.py",
        "ladder_dragon/supervision/recovery_gate.py",
        "ladder_dragon/supervision/process_manager.py",
        "ladder_dragon/supervision/prediction_shadow.py",
        "ladder_dragon/supervision/preflight_resilience.py",
        "ladder_dragon/execution/worker/bootstrap.py",
        "ladder_dragon/execution/worker/lifecycle.py",
        "ladder_dragon/execution/worker/event_loop.py",
        "ladder_dragon/execution/worker/buy_service.py",
        "ladder_dragon/execution/worker/holdings_service.py",
        "ladder_dragon/execution/worker/panic_control.py",
        "ladder_dragon/execution/worker/stats_sync.py",
        "ladder_dragon/dashboard/app_factory.py",
        "ladder_dragon/dashboard/repositories/trades.py",
        "ladder_dragon/execution/journal/connection.py",
        "ladder_dragon/execution/journal/lifecycle.py",
        "ladder_dragon/strategy/prediction/models.py",
        "ladder_dragon/strategy/prediction/walk_forward.py",
        "ladder_dragon/ai/context/decision_repository.py",
        "ladder_dragon/execution/orders/otoco.py",
        "ladder_dragon/execution/protection/emergency_flatten.py",
        "ladder_dragon/verification/live/mainnet_canary.py",
        "docs/LOCAL_ARTIFACTS.md",
    )
    assert [path for path in required if not (ROOT / path).is_file()] == []


def test_component_tests_replace_the_previous_test_monoliths():
    budgets = {
        "tests/test_safety_gates.py": 1093,
        "tests/supervision/test_supervisor_recovery.py": 1260,
        "tests/test_dashboard_security.py": 950,
        "tests/dashboard/test_dashboard_presentation.py": 700,
        "tests/test_module_boundaries.py": 620,
        "tests/execution/test_order_boundaries.py": 1000,
        "tests/test_order_recovery.py": 820,
        "tests/execution/test_order_recovery_lifecycle.py": 450,
    }
    assert {
        path: (_line_count(path), limit)
        for path, limit in budgets.items()
        if _line_count(path) > limit
    } == {}
    assert (ROOT / "tests/support/module_loaders.py").is_file()
