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
