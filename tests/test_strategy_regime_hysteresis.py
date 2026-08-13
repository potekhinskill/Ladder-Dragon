from ladder_dragon.strategy import strategy_math
from ladder_dragon.strategy.strategy_math import RegimeHysteresis


def test_initial_regime_change_observes_process_hold(monkeypatch):
    monkeypatch.setattr(strategy_math.time, "monotonic", lambda: 10_000.0)
    hysteresis = RegimeHysteresis(
        "FLAT",
        min_hold_sec=300,
        confirmations=2,
    )

    assert hysteresis.update("DOWN", now=10_001) == "FLAT"
    assert hysteresis.update("DOWN", now=10_002) == "FLAT"
    assert hysteresis.update("DOWN", now=10_299) == "FLAT"
    assert hysteresis.update("DOWN", now=10_300) == "DOWN"


def test_zero_hold_preserves_immediate_confirmed_transition(monkeypatch):
    monkeypatch.setattr(strategy_math.time, "monotonic", lambda: 10_000.0)
    hysteresis = RegimeHysteresis(
        "FLAT",
        min_hold_sec=0,
        confirmations=2,
    )

    assert hysteresis.update("UP", now=10_001) == "FLAT"
    assert hysteresis.update("UP", now=10_002) == "UP"
