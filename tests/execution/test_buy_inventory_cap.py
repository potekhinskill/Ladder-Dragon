from decimal import Decimal

from ladder_dragon.execution.worker.buy_service import place_buys
from tests.support.module_loaders import load_worker


def test_live_buy_cannot_cross_remaining_inventory_hard_cap(monkeypatch):
    worker = load_worker()
    worker.RUN = True
    monkeypatch.setenv("RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT", "30")
    monkeypatch.setattr(worker, "get_symbol_assets", lambda _symbol: ("SOL", "USDT"))
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(worker, "pull_filters", lambda _symbol: None)
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {
            "SOL": {"free": "0.2999", "locked": "0"},
            "USDT": {"free": "100", "locked": "0"},
        },
    )
    monkeypatch.setattr(worker, "get_price_exact", lambda _symbol: Decimal("100"))
    monkeypatch.setattr(worker, "list_open_orders", lambda _symbol: [])
    monkeypatch.setattr(
        worker,
        "place_limit_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("BUY crossed the absolute inventory CAP")
        ),
    )

    assert place_buys(
        "SOLUSDT",
        [90.0],
        10.0,
        target_buy_per_symbol=1,
        live_mode=True,
        runtime=vars(worker),
    ) == []
