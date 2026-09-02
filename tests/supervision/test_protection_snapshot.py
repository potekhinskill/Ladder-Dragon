"""Authoritative open-order snapshot reuse regressions."""

from types import SimpleNamespace

import pytest

from ladder_dragon.supervision.protection_snapshot import verify_live_protection


class Journal:
    """Provide the minimum durable protection contract for this unit."""

    def __init__(self):
        self.protection = SimpleNamespace(
            client_order_id="LIST-1",
            symbol="SOLUSDT",
            order_type="OCO",
            exchange_order_list_id=700,
            metadata={},
        )
        self.metadata = None

    def protection_for_parent(self, _parent_id):
        return self.protection

    def update_metadata(self, _client_id, metadata):
        self.metadata = metadata


def order_list():
    """Return one active list with two authoritative references."""
    return {
        "orderListId": 700,
        "listClientOrderId": "LIST-1",
        "contingencyType": "OCO",
        "listStatusType": "EXEC_STARTED",
        "orders": [
            {"orderId": 701, "symbol": "SOLUSDT"},
            {"orderId": 702, "symbol": "SOLUSDT"},
        ],
    }


def open_leg(order_id, leg_type):
    """Return one complete open-order snapshot row."""
    return {
        "orderId": order_id,
        "orderListId": 700,
        "clientOrderId": f"LEG-{order_id}",
        "symbol": "SOLUSDT",
        "side": "SELL",
        "type": leg_type,
        "status": "NEW",
    }


def active_legs(_legs):
    """Classify the fixture legs as active."""
    return "ACTIVE", None, None


def test_complete_snapshot_avoids_repeated_exact_leg_reads():
    journal = Journal()
    calls = []

    def signed_get(path, params):
        calls.append((path, dict(params)))
        if path != "/api/v3/orderList":
            pytest.fail("complete open-order snapshot was not reused")
        return order_list()

    result = verify_live_protection(
        journal,
        "BUY-1",
        open_orders=[
            open_leg(701, "LIMIT_MAKER"),
            open_leg(702, "STOP_LOSS_LIMIT"),
        ],
        signed_get=signed_get,
        classify_oco_legs=active_legs,
        now_epoch=lambda: 123,
    )

    assert result == 3
    assert [path for path, _params in calls] == ["/api/v3/orderList"]
    assert journal.metadata["startup_exchange_verified_at"] == 123


def test_incomplete_snapshot_falls_back_to_every_exact_leg_read():
    journal = Journal()
    calls = []

    def signed_get(path, params):
        calls.append((path, dict(params)))
        if path == "/api/v3/orderList":
            return order_list()
        order_id = int(params["orderId"])
        return open_leg(
            order_id,
            "LIMIT_MAKER" if order_id == 701 else "STOP_LOSS_LIMIT",
        )

    incomplete = open_leg(701, "LIMIT_MAKER")
    incomplete.pop("type")
    result = verify_live_protection(
        journal,
        "BUY-1",
        open_orders=[incomplete],
        signed_get=signed_get,
        classify_oco_legs=active_legs,
        now_epoch=lambda: 123,
    )

    assert result == 3
    assert [path for path, _params in calls] == [
        "/api/v3/orderList",
        "/api/v3/order",
        "/api/v3/order",
    ]


def test_snapshot_symbol_mismatch_fails_closed_without_leg_fallback():
    journal = Journal()
    bad_leg = open_leg(701, "LIMIT_MAKER")
    bad_leg["symbol"] = "ETHUSDT"
    calls = []

    def signed_get(path, params):
        calls.append((path, dict(params)))
        return order_list()

    with pytest.raises(RuntimeError, match="symbol differs"):
        verify_live_protection(
            journal,
            "BUY-1",
            open_orders=[bad_leg],
            signed_get=signed_get,
            classify_oco_legs=active_legs,
            now_epoch=lambda: 123,
        )

    assert [path for path, _params in calls] == ["/api/v3/orderList"]


def test_otoco_snapshot_reuses_sells_and_queries_only_filled_working_buy():
    journal = Journal()
    journal.protection.order_type = "OTOCO"
    calls = []

    def signed_get(path, params):
        calls.append((path, dict(params)))
        if path == "/api/v3/orderList":
            payload = order_list()
            payload["contingencyType"] = "OTOCO"
            payload["orders"].insert(
                0, {"orderId": 700, "symbol": "SOLUSDT"}
            )
            return payload
        assert int(params["orderId"]) == 700
        return {
            "orderId": 700,
            "orderListId": 700,
            "clientOrderId": "BUY-1",
            "symbol": "SOLUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "status": "FILLED",
        }

    result = verify_live_protection(
        journal,
        "BUY-1",
        open_orders=[
            open_leg(701, "LIMIT_MAKER"),
            open_leg(702, "STOP_LOSS_LIMIT"),
        ],
        signed_get=signed_get,
        classify_oco_legs=active_legs,
        now_epoch=lambda: 123,
    )

    assert result == 3
    assert [path for path, _params in calls] == [
        "/api/v3/orderList",
        "/api/v3/order",
    ]


def test_complete_single_order_snapshot_avoids_exact_order_read():
    journal = Journal()
    journal.protection = SimpleNamespace(
        client_order_id="STOP-1",
        symbol="SOLUSDT",
        order_type="STOP_LOSS_LIMIT",
        exchange_order_id=901,
    )
    row = open_leg(901, "STOP_LOSS_LIMIT")
    row["orderListId"] = -1
    row["clientOrderId"] = "STOP-1"

    result = verify_live_protection(
        journal,
        "BUY-1",
        open_orders=[row],
        signed_get=lambda *_args, **_kwargs: pytest.fail(
            "complete single-order snapshot was not reused"
        ),
        classify_oco_legs=active_legs,
        now_epoch=lambda: 123,
    )

    assert result == 1
