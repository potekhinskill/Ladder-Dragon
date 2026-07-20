import ast
from pathlib import Path


FILES = (
    Path("bin/ai_supervisor.py"),
    Path("ladder_dragon/ai/ai_context.py"),
    Path("bin/autosize_universal.py"),
    Path("bin/binance_mainnet_canary.py"),
    Path("bin/stats_view.py"),
    Path("bin/tools_cancel_open.py"),
    Path("bin/ai_plan_runner.py"),
    Path("bin/auto_ladder_map.py"),
    Path("bin/gen_vwap_autotune.py"),
    Path("bin/ladder_pct_runner.py"),
    Path("bin/pnl_24h.py"),
    Path("ladder_dragon/execution/executor_protection.py"),
)


def _broad_exception_boundaries(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.functions: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.functions.append(node.name)
            self.generic_visit(node)
            self.functions.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                function = self.functions[-1] if self.functions else "<module>"
                found.add(f"{path.as_posix()}::{function}")
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


def test_broad_exception_handlers_are_limited_to_fail_closed_boundaries():
    found = set().union(*(_broad_exception_boundaries(path) for path in FILES))
    assert found == {
        "bin/autosize_universal.py::_panic_state_fail_closed",
        "bin/autosize_universal.py::_gap_watchdog_fail_closed",
        "bin/binance_mainnet_canary.py::run_canary",
        "ladder_dragon/execution/executor_protection.py::protect_filled_buys",
    }


def test_supervisor_financial_boundaries_do_not_call_float():
    tree = ast.parse(Path("bin/ai_supervisor.py").read_text())
    financial_functions = {
        "get_balances",
        "get_balances_full",
        "place_limit_order",
        "place_market_order",
        "_net_position_base",
        "_ensure_min_notional_qty",
        "position_guard_and_maybe_flatten",
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in financial_functions:
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "float"
            ):
                violations.append(f"{node.name}:{child.lineno}")
    assert violations == []


def test_executor_order_and_protection_modules_have_no_float_calls():
    for path in (
        Path("ladder_dragon/execution/executor_orders.py"),
        Path("ladder_dragon/execution/executor_protection.py"),
    ):
        tree = ast.parse(path.read_text())
        calls = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
        ]
        assert calls == [], f"{path} contains float() at {calls}"


def test_worker_financial_order_paths_have_no_float_calls():
    path = Path("bin/autosize_universal.py")
    tree = ast.parse(path.read_text())
    financial_functions = {
        "place_market_order",
        "place_limit_order",
        "place_oco_sell",
        "_round_price_exact",
        "_round_qty_exact",
        "_format_price_exact",
        "_format_qty_exact",
        "_minimum_qty_exact",
        "_minimum_notional_exact",
        "avg_entry",
        "_pick_ladder_aligned_oco_prices",
        "maybe_place_buys",
        "maybe_place_sells_from_holdings",
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in financial_functions:
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "float"
            ):
                violations.append(f"{node.name}:{child.lineno}")
    assert violations == []


def test_executor_balance_reader_has_no_float_calls():
    tree = ast.parse(Path(
        "ladder_dragon/execution/executor_market.py"
    ).read_text())
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_balances"
    )
    calls = [
        node.lineno
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]
    assert calls == []
