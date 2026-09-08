"""Complete current valuation routes take priority over unused alternatives."""

from decimal import Decimal

import pytest

from ladder_dragon.supervision import runtime
from tests.supervision.test_snapshot_tickers import snapshot_runtime
from tests.supervision.test_batch_tickers import batch_runtime


@pytest.mark.parametrize("bad", ["0", "NaN", "private-marker"])
def test_unused_alternative_does_not_block(monkeypatch, batch_runtime, bad):
    def public(path, params=None, **kwargs):
        if not params:
            return [{"symbol": "AAAUSDC", "price": "2"},
                    {"symbol": "AAABTC", "price": bad},
                    {"symbol": "BTCUSDT", "price": bad},
                    {"symbol": "BBBUSDT", "price": "2"}]
        if params["symbol"] == "SOLUSDT":
            return {"price": "75"}
        raise runtime.TM.BinanceHttpError(status=400, code=-1121)
    monkeypatch.setattr(runtime.TM, "_public_get", public)
    snapshot, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], batch_runtime)
    assert snapshot.equity_usdt == Decimal("109.992")


@pytest.mark.parametrize("eth_available", [True, False])
def test_complete_bridge_fallback(monkeypatch, snapshot_runtime, eth_available, capsys):
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {"AAA": {"free": "1", "locked": "0"}})
    reports, calls = {}, []
    monkeypatch.setattr(runtime, "_record_risk_startup_phase", lambda name, data: reports.update({name: data}))
    def read(symbol):
        calls.append(symbol)
        values = {"SOLUSDT": "75", "AAABTC": "2", "AAAETH": "2"}
        if eth_available:
            values["ETHUSDT"] = "10.123456789123456789"
        if symbol in values:
            return Decimal(values[symbol])
        raise RuntimeError("synthetic unavailable market")
    monkeypatch.setattr(runtime, "get_last_price_decimal", read)
    monkeypatch.setattr(runtime, "get_initial_last_price_decimal", read)
    if eth_available:
        for _ in range(2):
            snapshot, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
            assert snapshot.equity_usdt == Decimal("20.246913578246913578")
        assert calls.count("ETHUSDT") == 2  # No cross-snapshot price reuse.
    else:
        with pytest.raises(RuntimeError, match="synthetic unavailable market"):
            runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
    assert "ETHUSDT" in calls
    assert reports["valuation_routes"]["bridge_other_errors"] == (1 if eth_available else 2)
    assert "synthetic unavailable market" not in str(capsys.readouterr())
