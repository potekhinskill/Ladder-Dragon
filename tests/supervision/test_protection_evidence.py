"""Quantity and identity failures cannot create durable closure evidence."""

from decimal import Decimal
import pytest

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.executor_recovery import classify_oco_legs
from ladder_dragon.supervision.protection_snapshot import verify_live_protection


@pytest.fixture
def protection(tmp_path, request):
    path = tmp_path / "journal.sqlite3"
    journal = OrderJournal(path, venue="mainnet")
    journal.prepare(client_order_id="BUY-1", symbol="SOLUSDT", side="BUY",
                    purpose="ladder", order_type="LIMIT", quantity="0.1", price="100")
    journal.record_exchange_order("BUY-1", {"orderId": 110, "status": "FILLED", "executedQty": "0.1"})
    journal.prepare(client_order_id="LIST-1", symbol="SOLUSDT", side="SELL", purpose="oco",
                    order_type="OCO", quantity=getattr(request, "param", "0.1"), price="102", parent_client_order_id="BUY-1")
    journal.record_order_list("LIST-1", {"orderListId": 120, "listStatusType": "EXEC_STARTED"})
    legs = [dict(orderId=121+i, clientOrderId=f"LEG-{i}", symbol="SOLUSDT", orderListId=120,
                 side="SELL", type=kind, status="NEW", origQty="0.1", executedQty="0")
            for i, kind in enumerate(("LIMIT_MAKER", "STOP_LOSS_LIMIT"))]
    journal.mark_verified_protected(parent_client_order_id="BUY-1",
                                   protection_client_order_id="LIST-1", legs=legs, order_list_id=120)
    payload = dict(orderListId=120, listClientOrderId="LIST-1", contingencyType="OCO",
                   listStatusType="EXEC_STARTED", orders=[dict(leg) for leg in legs])
    def verify():
        def read(endpoint, params):
            if endpoint == "/api/v3/orderList":
                return payload
            return legs[params["orderId"] - 121]
        return verify_live_protection(journal, "BUY-1", open_orders=[], signed_get=read,
                                     classify_oco_legs=classify_oco_legs, now_epoch=lambda: 1)
    return journal, path, legs, payload, verify


@pytest.mark.parametrize("value", [None, "0", "-1", "NaN", "Infinity", "private-marker", "0.04", "0.2"])
def test_bad_coverage(protection, value, capsys):
    journal, path, legs, _, verify = protection
    legs[0]["origQty"] = value
    with pytest.raises(RuntimeError) as caught:
        verify()
    assert "private-marker" not in str(caught.value) + str(capsys.readouterr())
    reloaded = OrderJournal(path, venue="mainnet").get("BUY-1")
    assert reloaded.state == "PROTECTED"
    assert not reloaded.metadata.get("exact_lifecycle")


@pytest.mark.parametrize("protection", ["0.1", "0.04"], indirect=True)
def test_small_filled_order(protection):
    journal, path, legs, payload, verify = protection
    payload["listStatusType"] = "ALL_DONE"
    legs[0].update(status="FILLED", origQty="0.04", executedQty="0.04")
    legs[1].update(status="CANCELED", origQty="0.04")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            verify()
        assert OrderJournal(path, venue="mainnet").get("BUY-1").state == "PROTECTED"


@pytest.mark.parametrize("order_id", [999, None, True, 121.0])
def test_wrong_leg_id(protection, order_id):
    _, _, legs, _, verify = protection
    legs[0]["orderId"] = order_id
    with pytest.raises(RuntimeError, match="ID"):
        verify()


def test_duplicate_reference(protection):
    _, _, _, payload, verify = protection
    payload["orders"][1] = dict(payload["orders"][0])
    with pytest.raises(RuntimeError, match="duplicate"):
        verify()


def test_exact_exit(protection):
    journal, path, legs, payload, verify = protection
    payload["listStatusType"] = "ALL_DONE"
    legs[0].update(status="FILLED", executedQty="0.1")
    legs[1]["status"] = "CANCELED"
    assert verify() == 0
    assert verify() == 0
    assert OrderJournal(path, venue="mainnet").get("BUY-1").metadata["exact_lifecycle"]


def test_active_partial(protection):
    _, _, legs, _, verify = protection
    legs[0].update(status="PARTIALLY_FILLED", executedQty="0.04")
    assert verify() == 3


@pytest.mark.parametrize("status", ["new", "partially_filled"])
def test_noncanonical_status_cannot_skip_residual_check(protection, status):
    journal, _, legs, _, verify = protection
    journal.partial_protection_exit_quantity = lambda parent: Decimal("0.04")
    for leg in legs:
        leg.update(status=status, executedQty="0.01" if status == "partially_filled" else "0")
    with pytest.raises(RuntimeError):
        verify()
    assert journal.get("BUY-1").state == "PROTECTED"


def test_prior_exit_coverage(protection):
    journal, _, legs, payload, verify = protection
    journal.partial_protection_exit_quantity = lambda parent: Decimal("0.04")
    # Old full-size protection cannot over-sell the residual after replacement.
    with pytest.raises(RuntimeError, match="residual"):
        verify()


def test_real_residual_replacement(protection):
    journal, path, legs, payload, _ = protection
    journal.record_partial_protection_exit(protection_client_order_id="LIST-1", exit_order_id=121,
        exit_reason="TP", executed_qty="0.04", terminal_status="CANCELED")
    journal.prepare(client_order_id="LIST-2", symbol="SOLUSDT", side="SELL", purpose="oco",
        order_type="OCO", quantity="0.06", price="102", parent_client_order_id="BUY-1")
    for index, leg in enumerate(legs):
        leg.update(orderId=221+index, orderListId=220, clientOrderId=f"NEW-{index}", origQty="0.06")
    journal.mark_verified_protected(parent_client_order_id="BUY-1", protection_client_order_id="LIST-2",
        legs=legs, order_list_id=220)
    payload.update(orderListId=220, listClientOrderId="LIST-2", orders=legs)
    def read(endpoint, params):
        return payload if endpoint.endswith("orderList") else legs[params["orderId"]-221]
    for closed in (False, True, True):
        if closed:
            legs[0].update(status="FILLED", executedQty="0.06")
            legs[1]["status"] = "CANCELED"
            payload["listStatusType"] = "ALL_DONE"
        reloaded = OrderJournal(path, venue="mainnet")
        assert verify_live_protection(reloaded, "BUY-1", open_orders=[], signed_get=read,
            classify_oco_legs=classify_oco_legs, now_epoch=lambda: 1) == (0 if closed else 3)
    assert reloaded.get("BUY-1").metadata["exact_lifecycle"]
