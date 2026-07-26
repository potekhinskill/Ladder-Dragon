import pytest

from decimal import Decimal

from ladder_dragon.risk.risk_statistics import (
    allocate_cap_by_marginal_risk_decimal,
    conversion_price_decimal,
    correlated_symbols,
    correlation_clusters_multi_window,
    liquidity_is_sufficient_decimal,
    rolling_correlation,
    stress_exposure,
    stress_loss_decimal,
)


def test_rolling_correlation_detects_common_shock():
    left = [100, 101, 99, 102, 103, 101, 104]
    right = [50, 50.5, 49.5, 51, 51.5, 50.5, 52]
    assert rolling_correlation(left, right, window=6) > 0.9
    assert correlated_symbols({"BTCUSDT": left, "ETHUSDT": right}) == {
        "BTCUSDT", "ETHUSDT"
    }


def test_correlation_clusters_keep_independent_assets_separate():
    common = [100, 101, 99, 102, 103, 101, 104]
    matching = [50, 50.5, 49.5, 51, 51.5, 50.5, 52]
    independent = [10, 9, 10, 9, 10, 9, 10]

    assert correlation_clusters_multi_window(
        {
            "BTCUSDT": common,
            "ETHUSDT": matching,
            "XRPUSDT": independent,
        },
        windows=(3, 4, 6),
        min_windows=2,
    ) == (("BTCUSDT", "ETHUSDT"),)


def test_liquidity_gate_checks_both_spread_and_two_sided_depth():
    values = {
        "best_bid": "99.95",
        "best_ask": "100.05",
        "bid_depth_quote": "10000",
        "ask_depth_quote": "9000",
        "max_spread_bps": "20",
        "min_depth_quote": "5000",
    }
    assert liquidity_is_sufficient_decimal(**values) is True
    assert liquidity_is_sufficient_decimal(
        **{**values, "ask_depth_quote": "100"}
    ) is False


def test_stress_exposure_is_explicit_and_reproducible():
    assert stress_exposure(1000, (-0.30, -0.10, 0.10)) == pytest.approx(
        [700, 900, 1100]
    )


def test_financial_risk_helpers_preserve_decimal_precision():
    price = conversion_price_decimal(
        asset_qty="0.3", side="SELL",
        bids=[("10.000000000000000001", "0.1"), ("9.9", "0.2")],
        asks=[], fee_pct="0.001",
    )
    assert price == Decimal("9.923400000000000000333")
    assert stress_loss_decimal(
        {"SOLUSDT": "123.456789123456789"},
        price_shock="-0.05", spread_widening="0.01",
    ) == Decimal("7.40740734740740734")


def test_marginal_risk_cap_allocation_is_exact():
    result = allocate_cap_by_marginal_risk_decimal(
        "10.000000000000000001",
        {"SOLUSDT": "2", "ETHUSDT": "1"},
    )

    assert sum(result.values(), Decimal("0")) == Decimal(
        "10.00000000000000000100000000"
    )
    assert abs(
        result["ETHUSDT"] - result["SOLUSDT"] * Decimal("2")
    ) <= Decimal("0.000000000000000000000000001")
