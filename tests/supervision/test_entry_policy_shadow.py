import inspect
from decimal import Decimal

import pytest

from ladder_dragon.supervision import entry_policy
from ladder_dragon.supervision import runtime


def _volatile_settings(**updates):
    values = {
        "base_gap": "0.004",
        "atr_pct": "0.02",
        "base_min_profit": "0.002",
        "auto_adapt": True,
        "gap_atr_coefficient": "0.6",
        "profit_atr_coefficient": "0.6",
        "gap_floor": "0.0025",
        "gap_ceiling": "0.02",
        "mode": "UP",
        "up_gap_multiplier": "0.80",
        "down_gap_multiplier": "1.50",
        "take_profit_pct": "0.006",
        "up_tp_multiplier": "1.00",
        "down_tp_multiplier": "1.00",
        "tp_floor": "0.003",
        "tp_ceiling": "0.009",
    }
    values.update(updates)
    return values


def test_execution_rejects_profit_floor_above_tp_ceiling():
    with pytest.raises(ValueError, match="minimum profitable TP"):
        entry_policy.directional_entry_settings(**_volatile_settings())


def test_shadow_observation_preserves_the_configured_tp_ceiling():
    gap, minimum_profit, take_profit = (
        entry_policy.directional_entry_settings(
            **_volatile_settings(allow_observation_clamp=True)
        )
    )

    assert gap == Decimal("0.00960")
    assert minimum_profit == Decimal("0.012")
    assert take_profit == Decimal("0.009")


def test_runtime_allows_the_clamp_only_without_execution_authority():
    source = inspect.getsource(runtime.run_for_symbol)

    assert "allow_observation_clamp=not execution_allowed" in source
