"""Incomplete remote state never becomes empty or zero financial exposure."""

from decimal import Decimal
import pytest

from ladder_dragon.supervision.open_order_snapshot import checked_open_orders
from ladder_dragon.supervision import runtime
from tests.supervision.test_snapshot_tickers import snapshot_runtime


def row():
    return dict(symbol="SOLUSDT", orderId=1, orderListId=-1, clientOrderId="BUY-1",
                side="BUY", type="LIMIT", status="NEW", price="75", origQty="1", executedQty="0")


@pytest.mark.parametrize("payload", [None, {}, False, 0, "", [None], [row(), row()]])
def test_collection_rejected(monkeypatch, snapshot_runtime, payload):
    monkeypatch.setattr(runtime, "get_initial_last_price_decimal", lambda symbol: Decimal("75"))
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {"USDT": {"free": "100", "locked": "0"}})
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda *a, **kw: payload)
    with pytest.raises(ValueError, match="invalid open-orders snapshot"):
        runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)


@pytest.mark.parametrize("field", list(row()))
def test_missing_field(field):
    value = row()
    value.pop(field)
    with pytest.raises(ValueError):
        checked_open_orders([value])


@pytest.mark.parametrize("field,value", [("orderId", True), ("orderId", 1.5),
    ("side", "private-marker"), ("price", "0"), ("price", "NaN"),
    ("origQty", "0"), ("executedQty", "2"), ("status", "FILLED")])
def test_invalid_fields(field, value, capsys):
    order = row()
    order[field] = value
    with pytest.raises(ValueError) as caught:
        checked_open_orders([order])
    assert "private-marker" not in str(caught.value) + str(capsys.readouterr())


def test_empty_and_partial():
    assert checked_open_orders([]) == []
    order = row()
    order.update(status="PARTIALLY_FILLED", executedQty="0.4")
    checked = checked_open_orders([order])
    assert checked == [order] and checked[0] is not order


@pytest.mark.parametrize("symbol", [None, "ETHUSDT", "solusdt", "private-marker", True])
def test_ticker_identity(monkeypatch, symbol, capsys):
    monkeypatch.setattr(runtime.TM, "_public_get", lambda *a, **kw: {"symbol": symbol, "price": "3000"})
    with pytest.raises(ValueError, match="ticker symbol") as caught:
        runtime.get_last_price_decimal("SOLUSDT")
    assert "private-marker" not in str(caught.value) + str(capsys.readouterr())
