"""Require every exact closure path to deliver evidence to the final guard."""

import ast
from pathlib import Path
import pytest
from ladder_dragon.verification.source_contracts import qualified_functions, expression_identity

ROOT = Path(__file__).resolve().parents[2]


def guarded_writer(source):
    method = qualified_functions(ast.parse(source))["OrderJournal.mark_exact_lifecycle_closed"]
    transactions = [node for node in method.body if isinstance(node, ast.With)]
    if len(transactions) != 1:
        return False
    statements = transactions[0].body
    guards = [i for i, node in enumerate(statements) if isinstance(node, ast.Expr)
              and isinstance(node.value, ast.Call)
              and expression_identity(node.value.func) == "require_exact_exit"]
    writes = [i for i, node in enumerate(statements) if any(
        isinstance(item, ast.Call) and expression_identity(item.func) in {"self._update_row", "con.execute"}
        for item in ast.walk(node))]
    return len(guards) == 1 and bool(writes) and guards[0] < min(writes)


def test_exact_writer_guard_is_direct_and_precedes_database_writes():
    source = (ROOT / "ladder_dragon/execution/order_recovery.py").read_text()
    assert guarded_writer(source)
    call = "            require_exact_exit(con, parent, protection, exit_order, exit_order_id, self.venue)"
    assert call in source
    assert not guarded_writer(source.replace(call, "            pass"))
    assert not guarded_writer(source.replace(call, "            def decoy():\n    " + call))
    assert not guarded_writer(source.replace(call, "            if False:\n    " + call))


def test_every_production_exact_closure_supplies_observed_exit():
    callers = []
    for path in (ROOT / "ladder_dragon").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "mark_exact_lifecycle_closed"):
                supplied = [kw.value for kw in node.keywords if kw.arg == "exit_order"]
                assert len(supplied) == 1 and not isinstance(supplied[0], ast.Constant), path
                callers.append(path.relative_to(ROOT).as_posix())
    assert set(callers) == {
        "ladder_dragon/execution/executor_recovery.py", "ladder_dragon/execution/orders/runtime.py",
        "ladder_dragon/execution/worker/stats_sync.py", "ladder_dragon/supervision/protection_snapshot.py"}
