"""Fail-closed tests for worker exchange lookups."""

from decimal import Decimal
from types import SimpleNamespace

import requests

from ladder_dragon.execution.worker.event_loop import WorkerLoopContext
from ladder_dragon.execution.worker.time_stop import apply_time_stop
from tests.support.module_loaders import load_worker
from tests.test_worker_order_recovery import configure_worker, _journal_buy


def test_panic_initial_lookup_failure_halts_before_cancel(tmp_path, monkeypatch):
    worker = load_worker()
    configure_worker(worker, tmp_path, monkeypatch)
    _journal_buy(worker._ORDER_JOURNAL, order_id=201)
    delete_calls = []
    monkeypatch.setattr(
        worker,
        "get_order",
        lambda *_args: (_ for _ in ()).throw(
            requests.ConnectionError("private endpoint omitted")
        ),
    )
    monkeypatch.setattr(
        worker,
        "_signed_request",
        lambda *args, **_kwargs: delete_calls.append(args),
    )

    try:
        worker.cancel_open_buys_for_panic("SOLUSDT", [201])
    except RuntimeError as exc:
        assert str(exc) == "panic cancel cannot confirm BUY order 201"
    else:
        raise AssertionError("PANIC cancellation lookup must fail closed")

    assert delete_calls == []
    assert (tmp_path / "circuit_halt.json").exists()


def test_panic_reconciliation_lookup_failure_halts(tmp_path, monkeypatch):
    worker = load_worker()
    configure_worker(worker, tmp_path, monkeypatch)
    _journal_buy(worker._ORDER_JOURNAL, order_id=202)
    responses = iter(
        [
            {
                "symbol": "SOLUSDT",
                "side": "BUY",
                "orderId": 202,
                "status": "NEW",
                "executedQty": "0",
            },
            requests.ConnectionError("private endpoint omitted"),
        ]
    )

    def get_order(*_args):
        response = next(responses)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(worker, "get_order", get_order)
    monkeypatch.setattr(
        worker,
        "_signed_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.ConnectionError("cancel response omitted")
        ),
    )

    try:
        worker.cancel_open_buys_for_panic("SOLUSDT", [202])
    except RuntimeError as exc:
        assert str(exc) == "panic cancel cannot confirm BUY order 202"
    else:
        raise AssertionError("PANIC reconciliation lookup must fail closed")

    assert (tmp_path / "circuit_halt.json").exists()


def test_time_stop_lookup_failure_halts_and_preserves_queue():
    halts = []
    market_orders = []
    state = SimpleNamespace(
        LIVE_MODE=True,
        getenv_float=lambda name, default: Decimal("30"),
        time=SimpleNamespace(time=lambda: 1_000),
        requests=requests,
        get_order=lambda *_args: (_ for _ in ()).throw(
            requests.ConnectionError("private endpoint omitted")
        ),
        _trip_execution_halt=lambda reason, **metadata: halts.append(
            (reason, metadata)
        ),
        place_market_order=lambda *_args, **_kwargs: market_orders.append(True),
    )
    context = WorkerLoopContext(
        state=state,
        args=SimpleNamespace(),
        symbol="SOLUSDT",
        attach_oco=True,
        ladder_prices=[],
        placed_ids=[301, 302],
        panic_active=False,
        panic_sell_floor_pct=None,
        breakeven=SimpleNamespace(),
        breakeven_state=None,
        user_stream_mailbox=None,
        user_stream_observer=None,
        started_at=0,
        protection_state="pending",
    )

    apply_time_stop(context)

    assert context.placed_ids == [301, 302]
    assert market_orders == []
    assert halts == [
        (
            "time stop cannot confirm BUY order 301",
            {
                "symbol": "SOLUSDT",
                "order_id": 301,
                "error_type": "ConnectionError",
            },
        )
    ]
