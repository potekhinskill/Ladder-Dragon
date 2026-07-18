import importlib.util
from pathlib import Path

import requests

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
    return worker._ORDER_JOURNAL



def test_protection_dependencies_expose_market_flatten_after_restart(tmp_path, monkeypatch):
    worker = load_worker()
    configure_worker(worker, tmp_path, monkeypatch)
    dependencies = worker._protection_dependencies()
    assert callable(dependencies.place_market_order)


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
