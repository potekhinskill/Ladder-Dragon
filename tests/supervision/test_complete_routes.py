"""Only complete current routes can suppress later network observations."""

from decimal import Decimal
import pytest

from ladder_dragon.execution.market_tickers import valuation_prices
from ladder_dragon.supervision.valuation_reads import ValuationReads


@pytest.mark.parametrize("bad", ["0", "NaN", "private-marker"])
@pytest.mark.parametrize("field", ["AAABTC", "BTCUSDT"])
def test_valid_alternate(field, bad, capsys):
    values = {"AAABTC": "1", "BTCUSDT": "2", "AAAETH": "3", "ETHUSDT": "4"}
    values[field] = bad
    payload = [dict(symbol=symbol, price=price) for symbol, price in values.items()]
    prices = valuation_prices(payload, {"AAAUSDT"})
    assert prices == {"AAAETH": Decimal("3"), "ETHUSDT": Decimal("4")}
    assert "private-marker" not in repr(prices) + str(capsys.readouterr())


def test_all_invalid_block():
    with pytest.raises(ValueError):
        valuation_prices([dict(symbol="AAABTC", price="0")], {"AAAUSDT"})


def test_stable_short_circuit():
    calls = []
    reads = ValuationReads(6)
    try:
        for result in reads.routes(("USDC", "FDUSD", "BTC", "ETH"), lambda quote: calls.append(quote) or 1):
            if result:
                break
    finally:
        reads.close()
    assert calls == ["USDC"]
