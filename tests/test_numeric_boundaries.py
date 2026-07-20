from pathlib import Path

import pytest

from bin.audit_numeric_boundaries import audit_numeric_boundaries
from ladder_dragon.numeric_compat import compatibility_float


def test_financial_module_float_calls_do_not_regress():
    root = Path(__file__).resolve().parents[1]
    report = audit_numeric_boundaries(root)

    assert report["ready"] is True
    assert report["counts"][
        "ladder_dragon/execution/executor_orders.py"
    ] == 0
    assert report["counts"][
        "ladder_dragon/execution/executor_protection.py"
    ] == 0
    assert report["counts"]["bin/ai_supervisor.py"] == 0
    assert report["counts"]["bin/autosize_universal.py"] == 0
    assert report["counts"]["ladder_dragon/ai/ai_context.py"] == 0
    assert report["counts"]["ladder_dragon/numeric_compat.py"] == 1


def test_numeric_compatibility_boundary_rejects_non_finite_values():
    assert compatibility_float("0.125") == 0.125
    with pytest.raises(ValueError, match="finite"):
        compatibility_float("NaN")
    with pytest.raises(ValueError, match="finite"):
        compatibility_float("Infinity")
