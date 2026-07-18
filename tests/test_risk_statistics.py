import pytest

from ladder_dragon.risk.risk_statistics import correlated_symbols, rolling_correlation, stress_exposure


def test_rolling_correlation_detects_common_shock():
    left = [100, 101, 99, 102, 103, 101, 104]
    right = [50, 50.5, 49.5, 51, 51.5, 50.5, 52]
    assert rolling_correlation(left, right, window=6) > 0.9
    assert correlated_symbols({"BTCUSDT": left, "ETHUSDT": right}) == {
        "BTCUSDT", "ETHUSDT"
    }


def test_stress_exposure_is_explicit_and_reproducible():
    assert stress_exposure(1000, (-0.30, -0.10, 0.10)) == pytest.approx(
        [700, 900, 1100]
    )
