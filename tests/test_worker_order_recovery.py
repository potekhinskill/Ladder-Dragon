import importlib.util
import sqlite3
from pathlib import Path

import pytest
import requests

from ladder_dragon.execution.binance_transport import BinanceResponseError
from ladder_dragon.execution.order_recovery import OrderJournal


def load_worker():
    path = Path("bin/autosize_universal.py").resolve()
    spec = importlib.util.spec_from_file_location("recovery_worker", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def configure_worker(worker, tmp_path, monkeypatch):
    # Tests must not inherit the production circuit-breaker paths from systemd.
    # Otherwise an unconfirmed-order test could write a halt marker to
    # /run/mybot and stop the real bot instance.
    for name in ("CB_HALT_FILE", "CB_STATE_FILE", "CB_ALERTS_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    worker.LIVE_MODE = True
    worker._ORDER_JOURNAL = OrderJournal(tmp_path / "orders.sqlite3")
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(worker, "get_price", lambda symbol: 76.0)
    return worker._ORDER_JOURNAL



def test_protection_dependencies_expose_market_flatten_after_restart(tmp_path, monkeypatch):
    worker = load_worker()
    configure_worker(worker, tmp_path, monkeypatch)
    dependencies = worker._protection_dependencies()
    assert callable(dependencies.place_market_order)


def _journal_buy(journal, *, order_id=99, status="NEW", executed_qty="0"):
    intent = journal.prepare(
        client_order_id=f"LDBLAD-panic-{order_id}",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.126",
        price="75.80",
    )
    journal.record_exchange_order(
        intent.client_order_id,
        {
            "symbol": "SOLUSDT",
            "side": "BUY",
            "orderId": order_id,
            "status": status,
            "executedQty": executed_qty,
            "cummulativeQuoteQty": "0",
        },
    )
    return intent


def test_panic_cancels_unfilled_buy_and_updates_journal(tmp_path, monkeypatch):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    intent = _journal_buy(journal)
    calls = []

    monkeypatch.setattr(worker, "get_order", lambda symbol, order_id: {
        "symbol": symbol,
        "side": "BUY",
        "orderId": order_id,
        "status": "NEW",
        "executedQty": "0",
        "cummulativeQuoteQty": "0",
    })

    def signed(method, path, params=None, timeout=15):
        calls.append((method, path, params))
        return {
            "symbol": "SOLUSDT",
            "side": "BUY",
            "orderId": 99,
            "status": "CANCELED",
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
        }

    monkeypatch.setattr(worker, "_signed_request", signed)

    assert worker.cancel_open_buys_for_panic("SOLUSDT", [99]) == []
    assert calls == [
        ("DELETE", "/api/v3/order", {"symbol": "SOLUSDT", "orderId": 99})
    ]
    assert journal.get(intent.client_order_id).state == "CANCELED"


def test_buy_market_range_is_durable_for_nonfill_diagnostics(
    tmp_path, monkeypatch
):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    intent = _journal_buy(journal, order_id=102)
    worker._ORDER_OBSERVATION_LAST_WRITE.clear()

    worker._observe_buy_market("SOLUSDT", [102], 76.20)
    worker._ORDER_OBSERVATION_LAST_WRITE[102] = 0
    worker._observe_buy_market("SOLUSDT", [102], 75.90)

    observed = journal.get(intent.client_order_id)
    assert observed is not None
    assert observed.metadata["market_first_price"] == "76.2"
    assert observed.metadata["market_last_price"] == "75.9"
    assert observed.metadata["market_min_price"] == "75.9"
    assert observed.metadata["market_max_price"] == "76.2"
    assert observed.metadata["market_observation_count"] == 2


def test_panic_cancels_partial_remainder_and_keeps_fill_for_protection(
    tmp_path, monkeypatch
):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    intent = _journal_buy(
        journal, order_id=100, status="PARTIALLY_FILLED", executed_qty="0.020"
    )
    monkeypatch.setattr(worker, "get_order", lambda symbol, order_id: {
        "symbol": symbol,
        "side": "BUY",
        "orderId": order_id,
        "status": "PARTIALLY_FILLED",
        "executedQty": "0.020",
        "cummulativeQuoteQty": "1.5",
    })
    monkeypatch.setattr(worker, "_signed_request", lambda *args, **kwargs: {
        "symbol": "SOLUSDT",
        "side": "BUY",
        "orderId": 100,
        "status": "CANCELED",
        "executedQty": "0.020",
        "cummulativeQuoteQty": "1.5",
    })

    assert worker.cancel_open_buys_for_panic("SOLUSDT", [100]) == [100]
    assert journal.get(intent.client_order_id).state == "PROTECTION_PENDING"


def test_unconfirmed_panic_cancel_trips_persistent_halt(tmp_path, monkeypatch):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    _journal_buy(journal, order_id=101)
    monkeypatch.setattr(worker, "get_order", lambda symbol, order_id: {
        "symbol": symbol,
        "side": "BUY",
        "orderId": order_id,
        "status": "NEW",
        "executedQty": "0",
        "cummulativeQuoteQty": "0",
    })
    monkeypatch.setattr(
        worker,
        "_signed_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.ConnectionError("cancel response lost")
        ),
    )

    with pytest.raises(RuntimeError, match="panic cancel unconfirmed"):
        worker.cancel_open_buys_for_panic("SOLUSDT", [101])
    assert (tmp_path / "circuit_halt.json").exists()


def test_uncertain_limit_post_is_reconciled_and_not_duplicated(tmp_path, monkeypatch):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    calls = {"post": 0, "get": 0}

    def signed(method, path, params=None, timeout=15):
        if method == "POST":
            calls["post"] += 1
            persisted = journal.get(params["newClientOrderId"])
            assert persisted is not None and persisted.state == "PREPARED"
            raise requests.ConnectionError("response lost after exchange accepted order")
        calls["get"] += 1
        return {
            "symbol": "SOLUSDT",
            "orderId": 42,
            "clientOrderId": params["origClientOrderId"],
            "status": "NEW",
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
        }

    monkeypatch.setattr(worker, "_signed_request", signed)
    first = worker.place_limit_order("BUY", "SOLUSDT", 0.1, 100.0)
    second = worker.place_limit_order("BUY", "SOLUSDT", 0.1, 100.0)
    assert first["orderId"] == second["orderId"] == 42
    assert calls["post"] == 1
    assert calls["get"] == 2
    assert journal.get(first["clientOrderId"]).state == "SUBMITTED"


def test_uncertain_oco_post_uses_current_endpoint_and_recovers(tmp_path, monkeypatch):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    parent = journal.prepare(
        client_order_id="LDBLAD-parent",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    journal.record_exchange_order(
        parent.client_order_id,
        {
            "orderId": 41,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
    )
    observed = {}

    def signed(method, path, params=None, timeout=15):
        if method == "POST":
            observed.update(params)
            assert path == "/api/v3/orderList/oco"
            raise requests.ConnectionError("OCO ACK lost")
        if method == "GET" and path == "/api/v3/order":
            order_type = "LIMIT_MAKER" if params["orderId"] == 78 else "STOP_LOSS_LIMIT"
            return {
                "symbol": "SOLUSDT",
                "orderId": params["orderId"],
                "side": "SELL",
                "type": order_type,
                "status": "NEW",
            }
        assert method == "GET" and path == "/api/v3/orderList"
        return {
            "orderListId": 77,
            "listClientOrderId": params["origClientOrderId"],
            "listStatusType": "EXEC_STARTED",
            "orders": [
                {"symbol": "SOLUSDT", "orderId": 78, "clientOrderId": "tp"},
                {"symbol": "SOLUSDT", "orderId": 79, "clientOrderId": "sl"},
            ],
        }

    monkeypatch.setattr(worker, "_signed_request", signed)
    recovered = worker.place_oco_sell(
        "SOLUSDT",
        0.1,
        110.0,
        95.0,
        94.0,
        parent_client_order_id=parent.client_order_id,
    )
    assert recovered["orderListId"] == 77
    assert observed["aboveType"] == "LIMIT_MAKER"
    assert observed["belowType"] == "STOP_LOSS_LIMIT"
    assert "stopLimitPrice" not in observed
    assert journal.get(parent.client_order_id).state == "PROTECTED"


def test_partial_fill_is_recovered_after_restart(tmp_path, monkeypatch):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    intent = journal.prepare(
        client_order_id="LDBLAD-partial",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    journal.record_exchange_order(
        intent.client_order_id,
        {
            "orderId": 55,
            "status": "PARTIALLY_FILLED",
            "executedQty": "0.050",
            "cummulativeQuoteQty": "5.0",
        },
    )
    monkeypatch.setattr(
        worker,
        "get_order_by_client_id",
        lambda symbol, client_id: {
            "orderId": 55,
            "clientOrderId": client_id,
            "status": "PARTIALLY_FILLED",
            "executedQty": "0.050",
            "cummulativeQuoteQty": "5.0",
        },
    )
    assert worker.recover_pending_buy_order_ids("SOLUSDT") == [55]


def test_uncertain_unconfirmed_post_trips_persistent_halt(tmp_path, monkeypatch):
    worker = load_worker()
    configure_worker(worker, tmp_path, monkeypatch)
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))

    def signed(method, path, params=None, timeout=15):
        if method == "POST":
            raise requests.ConnectionError("ACK and reconciliation unavailable")
        return None

    monkeypatch.setattr(worker, "_signed_request", signed)
    try:
        worker.place_limit_order("BUY", "SOLUSDT", 0.1, 100.0)
    except requests.ConnectionError:
        pass
    else:
        raise AssertionError("uncertain submission must fail closed")
    assert (tmp_path / "circuit_halt.json").exists()


def test_definitive_binance_rejection_marks_failed_without_halt(tmp_path, monkeypatch):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    response = requests.Response()
    response.status_code = 400
    error = BinanceResponseError(
        status=400,
        code=-1013,
        message="Filter failure: PERCENT_PRICE_BY_SIDE",
        endpoint="/api/v3/order",
        response=response,
    )

    def signed(method, path, params=None, timeout=15):
        assert method == "POST"
        raise error

    monkeypatch.setattr(worker, "_signed_request", signed)
    with pytest.raises(BinanceResponseError):
        worker.place_limit_order("SELL", "SOLUSDT", 0.1, 232.12)

    with sqlite3.connect(journal.path) as connection:
        state, last_error = connection.execute(
            "SELECT state, last_error FROM order_intents"
        ).fetchone()
    assert state == "FAILED"
    assert "PERCENT_PRICE_BY_SIDE" in last_error
    assert not (tmp_path / "circuit_halt.json").exists()


def test_invalid_oco_legs_never_mark_buy_protected(tmp_path, monkeypatch):
    worker = load_worker()
    journal = configure_worker(worker, tmp_path, monkeypatch)
    parent = journal.prepare(
        client_order_id="LDBLAD-invalid-oco",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.100",
        price="100.00",
    )
    journal.record_exchange_order(
        parent.client_order_id,
        {"orderId": 888, "status": "FILLED", "executedQty": "0.100"},
    )
    deletes = []

    def signed(method, path, params=None, timeout=15):
        if method == "POST":
            return {"orderListId": 900, "listStatusType": "EXEC_STARTED"}
        if method == "DELETE":
            deletes.append(params["orderListId"])
            return {"orderListId": params["orderListId"], "listStatusType": "ALL_DONE"}
        if path == "/api/v3/orderList":
            return {
                "orderListId": 900,
                "listStatusType": "EXEC_STARTED",
                "orders": [
                    {"symbol": "SOLUSDT", "orderId": 901},
                    {"symbol": "SOLUSDT", "orderId": 902},
                ],
            }
        return {
            "symbol": "SOLUSDT",
            "orderId": params["orderId"],
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "status": "NEW",
        }

    monkeypatch.setattr(worker, "_signed_request", signed)
    result = worker.place_oco_sell(
        "SOLUSDT",
        0.1,
        110.0,
        95.0,
        94.0,
        parent_client_order_id=parent.client_order_id,
    )
    assert result is None
    assert deletes == [900]
    assert journal.get(parent.client_order_id).state == "PROTECTION_PENDING"
