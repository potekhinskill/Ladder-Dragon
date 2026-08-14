import json

from tests.support.module_loaders import load_dashboard


def test_trade_summary_returns_local_totals_while_equity_refreshes(monkeypatch):
    module = load_dashboard(monkeypatch)

    class Connection:
        def close(self):
            return None

    monkeypatch.setattr(module, "_open_db", lambda: (Connection(), "test.db"))
    monkeypatch.setattr(module, "_load_trades", lambda connection, symbols: [])
    monkeypatch.setattr(
        module,
        "_fifo_realized_pnl",
        lambda rows, cutoff, fee, **kwargs: {
            "total_trades": 3,
            "buy_volume_usdt": 12.0,
            "sell_volume_usdt": 14.0,
            "fees_usdt": 0.03,
            "cashflow_pnl_usdt": 1.97,
            "realized_pnl_usdt": 1.25,
        },
    )
    monkeypatch.setattr(
        module._EQUITY_SUMMARY_CACHE,
        "get",
        lambda key, loader: (None, "refreshing", None),
    )

    payload = json.loads(module.trades_summary().body)

    assert payload["ok"] is True
    assert payload["total_trades"] == 3
    assert payload["realized_pnl_usdt"] == 1.25
    assert payload["cashflow_pnl_usdt"] == 1.97
    assert payload["equity_pnl_usdt"] is None
    assert payload["equity_cache_status"] == "refreshing"


def test_dashboard_marks_refreshing_portfolio_without_failing_trade_summary():
    script = open("FRONT/dashboard.js", encoding="utf-8").read()

    assert "d.equity_cache_status==='refreshing'" in script
    assert "d.equity_cache_status==='stale'" in script
