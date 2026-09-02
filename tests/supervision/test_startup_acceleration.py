"""Supervisor startup acceleration regressions."""

import inspect
import time

from ladder_dragon.supervision import runtime as ai_supervisor


def test_initial_cleanup_reuses_one_snapshot_and_skips_canceled_order(monkeypatch):
    now_ms = int(time.time() * 1000)
    orders = [
        {
            "symbol": "SOLUSDT", "orderId": 601, "side": "BUY",
            "type": "LIMIT", "price": "70.00",
            "updateTime": now_ms - 10_000,
        },
        {
            "symbol": "SOLUSDT", "orderId": 602, "side": "SELL",
            "type": "STOP_LOSS_LIMIT", "price": "69.00",
            "updateTime": now_ms - 86_400_000,
        },
    ]
    reads = []
    canceled = []
    monkeypatch.setenv("START_CLEANUP_OFFLADDER_GRACE_SEC", "0")
    monkeypatch.setattr(
        ai_supervisor,
        "list_open_orders",
        lambda symbol: reads.append(symbol) or orders,
    )
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda _symbol, order_id: canceled.append(order_id) or True,
    )

    result = ai_supervisor.initial_cleanup_orders(
        "SOLUSDT", 76.0, [75.0], 0.01, 900, 1, 1,
    )

    assert reads == ["SOLUSDT"]
    assert canceled == [601]
    assert result["startup"] == {"reviewed": 2, "canceled": 1}
    assert result["periodic"] == {"reviewed": 1, "canceled": 0}


def test_startup_vwap_refresh_runs_after_first_worker_plan():
    runtime_source = inspect.getsource(ai_supervisor.main)
    worker_loop = runtime_source.index("for sym in symbols:")
    refresh = runtime_source.index(
        "if now_loop >= next_vwap_refresh:", worker_loop
    )

    assert worker_loop < refresh
