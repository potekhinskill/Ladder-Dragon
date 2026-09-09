"""Exercise the production status expressions without running trading paths."""

import ast
import inspect
import textwrap
from decimal import Decimal

import pytest

from ladder_dragon.supervision import runtime
from ladder_dragon.supervision.expectancy_status import build_expectancy_status


@pytest.mark.parametrize("mode,required,passes,warning,blocks", [
    ("SHADOW", Decimal("0.0096"), False, "configured_returns_below_required_edge", False),
    ("APPLY", Decimal("0.0096"), False, "configured_returns_below_required_edge", True),
    ("APPLY", Decimal("0.0096"), True, None, False),
    ("SHADOW", None, False, "required_edge_unavailable", False),
    ("APPLY", None, False, "required_edge_unavailable", True),
])
def test_runtime_status_reports_warning_without_granting_permission(mode, required, passes, warning, blocks):
    tree = ast.parse(textwrap.dedent(inspect.getsource(runtime.run_for_symbol)))
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name) and node.func.id == "build_expectancy_status"]
    assert len(matches) == 1
    state = {"expectancy_mode": mode, "required_edge": required, "expectancy_configuration_passes": passes,
             "commission_error": "none", "maker_mode": "SHADOW", "minimum_profit": Decimal("0.0060"),
             "tp1_exact": Decimal("0.0090"), "build_expectancy_status": build_expectancy_status}
    result = eval(compile(ast.Expression(matches[0]), "status", "eval"), {"__builtins__": {}}, state)
    assert result == {"mode": mode, "required_edge_pct": str(required) if required is not None else None,
                      "commission_error": "none", "maker_policy_mode": "SHADOW", "configuration_passes": passes,
                      "configuration_warning": warning, "configuration_blocks_buys": blocks,
                      "configured_minimum_net_pct": "0.0060", "configured_take_profit_pct": "0.0090"}
