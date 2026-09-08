"""Documented UTF-8 asset names must not block a complete account snapshot."""

from decimal import Decimal
import pytest
from ladder_dragon.execution.exchange_evidence import checked_balances
from ladder_dragon.execution.executor_market import get_balances
from ladder_dragon.supervision import runtime


@pytest.mark.parametrize("asset", ["币安人生", "测试资产", "TÉST", "资产😀"])
@pytest.mark.parametrize("amount", ["0", "1.25"])
def test_utf8_asset_is_preserved_in_both_adapters(monkeypatch, asset, amount):
    account = {"balances": [dict(asset="USDT", free="10", locked="0"),
                            dict(asset=asset, free=amount, locked="0")]}
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda *a: account)
    worker = get_balances(signed_request=lambda *a: account)
    assert worker[asset]["free"] == Decimal(amount)
    assert runtime.get_balances()["USDT"] == Decimal("10")
    full = runtime.get_balances_full()
    assert (asset in full) == (Decimal(amount) > 0)
    if asset in full:
        assert full[asset] == worker[asset]


@pytest.mark.parametrize("asset", ["", None, "a b", "a\n", "a\u202e", "a\x00", "a" * 129])
def test_invalid_asset_shape_remains_fail_closed(asset):
    with pytest.raises(ValueError):
        checked_balances({"balances": [dict(asset=asset, free="0", locked="0")]})


@pytest.mark.parametrize("asset", ["USDT", "币安人生"])
def test_duplicate_utf8_asset_is_not_merged(asset):
    row = dict(asset=asset, free="0", locked="0")
    with pytest.raises(ValueError, match="duplicate"):
        checked_balances({"balances": [row, dict(row)]})
