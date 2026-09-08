"""Terminal partial exits remain durable, unresolved, and fail closed."""

from decimal import Decimal

import pytest

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.executor_recovery import classify_oco_legs
from ladder_dragon.supervision.protection_snapshot import verify_live_protection


@pytest.mark.parametrize("list_type", ["OCO", "OTOCO"])
@pytest.mark.parametrize("exit_index", [0, 1])
@pytest.mark.parametrize("terminal", ["CANCELED", "EXPIRED", "FILLED"])
def test_terminal_exit_preserves_residual(tmp_path, list_type, exit_index, terminal):
    path = tmp_path / "orders.sqlite3"
    journal = OrderJournal(path, venue="mainnet")
    journal.prepare(client_order_id="BUY-1", symbol="SOLUSDT", side="BUY",
                    purpose="ladder", order_type="LIMIT", quantity="0.1", price="100")
    journal.record_exchange_order("BUY-1", {"orderId": 110, "status": "FILLED", "executedQty": "0.1"})
    journal.prepare(client_order_id="LIST-1", symbol="SOLUSDT", side="SELL",
                    purpose="oco", order_type=list_type, quantity="0.1", price="102",
                    parent_client_order_id="BUY-1")
    journal.record_order_list("LIST-1", {"orderListId": 120, "listStatusType": "EXEC_STARTED"})
    legs = [dict(orderId=121 + i, clientOrderId=f"LEG-{i}", symbol="SOLUSDT",
                 orderListId=120, side="SELL", type=kind, status="CANCELED",
                 origQty="0.1", executedQty="0")
            for i, kind in enumerate(("LIMIT_MAKER", "STOP_LOSS_LIMIT"))]
    legs[exit_index].update(status=terminal, executedQty="0.1" if terminal == "FILLED" else "0.04")
    journal.mark_verified_protected(parent_client_order_id="BUY-1",
                                   protection_client_order_id="LIST-1", legs=legs, order_list_id=120)
    orders = list(legs)
    if list_type == "OTOCO":
        orders.append(dict(orderId=110, clientOrderId="BUY-1", symbol="SOLUSDT",
                           orderListId=120, side="BUY", status="FILLED"))

    def get(path, params):
        if path == "/api/v3/orderList":
            return dict(orderListId=120, listClientOrderId="LIST-1", contingencyType=list_type,
                        listStatusType="ALL_DONE", orders=orders)
        assert path == "/api/v3/order"  # No mutation adapter is available.
        return next(order for order in orders if order["orderId"] == params["orderId"])

    for _ in range(2):
        journal = OrderJournal(path, venue="mainnet")
        if terminal == "FILLED":
            assert verify_live_protection(journal, "BUY-1", open_orders=[], signed_get=get,
                classify_oco_legs=classify_oco_legs, now_epoch=lambda: 1) == 0
            assert journal.get("BUY-1").state == "CLOSED"
            assert journal.get("BUY-1").metadata["exact_lifecycle"] is True
        else:
            with pytest.raises(RuntimeError, match="residual protection"):
                verify_live_protection(journal, "BUY-1", open_orders=[], signed_get=get,
                    classify_oco_legs=classify_oco_legs, now_epoch=lambda: 1)
            assert journal.get("BUY-1").state == "PROTECTION_PENDING"
            assert not journal.get("BUY-1").metadata.get("exact_lifecycle", False)
            assert journal.partial_protection_exit_quantity("BUY-1") == Decimal("0.04")
