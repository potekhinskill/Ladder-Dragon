from pathlib import Path

import pytest

from bin.audit_numeric_boundaries import audit_numeric_boundaries
from ladder_dragon.numeric_compat import compatibility_float


def test_financial_module_float_calls_do_not_regress():
    root = Path(__file__).resolve().parents[1]
    report = audit_numeric_boundaries(root)

    assert report["ready"] is True
    assert report["counts"][
        "ladder_dragon/execution/orders/runtime.py"
    ] == 0
    assert report["counts"][
        "ladder_dragon/execution/protection/runtime.py"
    ] == 0
    assert report["counts"][
        "ladder_dragon/execution/protection/breakeven.py"
    ] == 0
    assert report["counts"]["ladder_dragon/supervision/runtime.py"] == 0
    assert (
        report["counts"]["ladder_dragon/execution/worker/runtime.py"] == 0
    )
    assert report["counts"]["ladder_dragon/ai/context/runtime.py"] == 0
    assert report["counts"]["ladder_dragon/numeric_compat.py"] == 1
    assert report["counts"]["ladder_dragon/risk/risk_manager.py"] == 6
    assert report["counts"]["ladder_dragon/supervision/risk_cycle.py"] == 0
    assert report["counts"][
        "ladder_dragon/execution/cost_basis_import.py"
    ] == 3
    assert report["counts"][
        "ladder_dragon/execution/commission_revaluation.py"
    ] == 1
    assert report["counts"][
        "ladder_dragon/execution/trade_accounting.py"
    ] == 0
    assert report["counts"][
        "ladder_dragon/execution/inventory_lots.py"
    ] == 0


def test_numeric_compatibility_boundary_rejects_non_finite_values():
    assert compatibility_float("0.125") == 0.125
    with pytest.raises(ValueError, match="finite"):
        compatibility_float("NaN")
    with pytest.raises(ValueError, match="finite"):
        compatibility_float("Infinity")


def test_new_exact_execution_module_has_zero_float_budget(tmp_path):
    package = tmp_path / "ladder_dragon/execution/orders"
    package.mkdir(parents=True)
    for relative in (
        "ladder_dragon/risk/risk_manager.py",
        "ladder_dragon/supervision/risk_cycle.py",
        "ladder_dragon/supervision/runtime.py",
        "ladder_dragon/execution/worker/runtime.py",
        "ladder_dragon/ai/context/runtime.py",
        "ladder_dragon/numeric_compat.py",
        "ladder_dragon/execution/cost_basis_import.py",
        "ladder_dragon/execution/commission_revaluation.py",
        "ladder_dragon/execution/trade_accounting.py",
        "ladder_dragon/execution/inventory_lots.py",
        "ladder_dragon/execution/orders/runtime.py",
        "ladder_dragon/execution/protection/runtime.py",
        "ladder_dragon/execution/protection/breakeven.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    candidate = package / "new_order_path.py"
    candidate.write_text("value = float('1.0')\n", encoding="utf-8")

    report = audit_numeric_boundaries(tmp_path)

    relative = "ladder_dragon/execution/orders/new_order_path.py"
    assert report["regressions"][relative] == {"actual": 1, "maximum": 0}
