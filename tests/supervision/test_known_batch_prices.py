"""Only current exact prices can suppress redundant batch value parsing."""

from decimal import Decimal

import pytest

from ladder_dragon.execution.market_tickers import valuation_prices


@pytest.mark.parametrize("invalid", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), "75", None, True])
def test_invalid_known_price_cannot_bypass_validation(invalid):
    with pytest.raises(ValueError, match="invalid current snapshot price"):
        valuation_prices([], {"AAAUSDT"}, known_prices={"BTCUSDT": invalid})


@pytest.mark.parametrize("invalid", ["0", "NaN", "private-marker"])
def test_needed_bridge_remains_strict_and_error_is_safe(invalid):
    payload = [{"symbol": "AAABTC", "price": "2"}, {"symbol": "BTCUSDT", "price": invalid}]
    with pytest.raises(ValueError, match="invalid batch ticker response") as exc:
        valuation_prices(payload, {"AAAUSDT"}, known_prices={"SOLUSDT": Decimal("75")})
    assert "private-marker" not in str(exc.value)


def test_known_prices_do_not_bypass_duplicate_row_validation():
    payload = [{"symbol": "BTCUSDT", "price": "0"}] * 2
    with pytest.raises(ValueError, match="invalid batch ticker response"):
        valuation_prices(payload, {"AAAUSDT"}, known_prices={"BTCUSDT": Decimal("75")})


def test_known_prices_are_not_mutated_or_retained_between_calls():
    payload = [{"symbol": "AAABTC", "price": "2"}, {"symbol": "BTCUSDT", "price": "0"}]
    known = {"BTCUSDT": Decimal("75")}
    assert valuation_prices(payload, {"AAAUSDT"}, known_prices=known) == {"AAABTC": Decimal("2")}
    assert known == {"BTCUSDT": Decimal("75")}
    with pytest.raises(ValueError, match="invalid batch ticker response"):
        valuation_prices(payload, {"AAAUSDT"})
