"""Exercise financial evidence at real worker adapters and the final writer."""

from decimal import Decimal
import pytest
import requests

from ladder_dragon.execution import executor_market, executor_recovery, executor_stats, tools_stats
from ladder_dragon.execution.exchange_evidence import checked_balances, checked_list
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.orders.runtime import OrderDependencies, place_oco_sell
from tests.support.exchange_evidence import exit_order, order_list


@pytest.fixture
def evidence(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(client_order_id="BUY", symbol="SOLUSDT", side="BUY", purpose="ladder",
                    order_type="LIMIT", quantity="0.1", price="100")
    journal.record_exchange_order("BUY", dict(orderId=10, status="FILLED", executedQty="0.1"))
    journal.prepare(client_order_id="LIST", symbol="SOLUSDT", side="SELL", purpose="oco:BUY",
                    order_type="OCO", quantity="0.1", price="102", parent_client_order_id="BUY")
    legs = [exit_order(121, "TP", kind="LIMIT_MAKER"), exit_order(122, "STOP", kind="STOP_LOSS_LIMIT")]
    for leg in legs:
        leg.update(status="NEW", executedQty="0")
    journal.mark_verified_protected(parent_client_order_id="BUY", protection_client_order_id="LIST",
                                   legs=legs, order_list_id=120)
    payload = order_list(120, "LIST", legs)
    yield journal, legs, payload
    journal.close()


def recovery(journal, legs, payload, verifier=None):
    return executor_recovery.RecoveryDependencies(
        journal=lambda: journal, get_order_by_client_id=lambda *_: None,
        get_order_list_by_client_id=lambda *_: payload,
        verify_oco_legs=verifier or (lambda *_: legs),
        cancel_oco=lambda *_: pytest.fail("read failure must not cancel protection"),
        halt=lambda *a, **k: None, logger=lambda _: None)


def placement(journal, legs, payload, verifier=None):
    return OrderDependencies(
        live=lambda: True, logger=lambda _: None, pull_filters=lambda _: None,
        round_price=lambda _, x: x, round_qty=lambda _, x: x,
        min_qty=lambda *_: Decimal("0.001"), min_notional=lambda *_: Decimal("5"),
        format_price=lambda _, x: str(x), format_qty=lambda _, x: str(x), journal=lambda: journal,
        signed_request=lambda *a, **k: pytest.fail("existing protection must not be mutated"),
        get_order_by_client_id=lambda *_: None, get_order_list_by_client_id=lambda *_: payload,
        verify_oco_legs=verifier or (lambda *_: legs),
        cancel_oco=lambda *_: pytest.fail("read failure must not cancel protection"),
        halt=lambda *a, **k: None, validate_limit_sell_prices=lambda *_: None)


@pytest.mark.parametrize("path", ["writer", "recovery", "placement"])
def test_small_filled_sell_cannot_close_buy(evidence, path):
    journal, legs, payload = evidence
    legs[0].update(status="FILLED", origQty="0.04", executedQty="0.04")
    legs[1].update(status="CANCELED", origQty="0.04")
    payload["listStatusType"] = "ALL_DONE"
    for _ in range(2):
        with pytest.raises(RuntimeError):
            if path == "writer":
                journal.mark_exact_lifecycle_closed(protection_client_order_id="LIST", exit_order_id=121,
                                                    exit_reason="TP", exit_order=legs[0])
            elif path == "recovery":
                executor_recovery.recover_existing_protection("BUY", dependencies=recovery(journal, legs, payload))
            else:
                place_oco_sell("SOLUSDT", Decimal("0.1"), Decimal("102"), Decimal("95"), Decimal("94"),
                               parent_client_order_id="BUY", dependencies=placement(journal, legs, payload))
        assert journal.get("BUY").state == "PROTECTED"
        assert not journal.get("BUY").metadata.get("exact_lifecycle")


def test_repeated_placement_records_partial_without_closing(evidence):
    journal, legs, payload = evidence
    legs[0].update(status="CANCELED", executedQty="0.04")
    legs[1]["status"] = "CANCELED"
    payload["listStatusType"] = "ALL_DONE"
    with pytest.raises(RuntimeError, match="residual"):
        place_oco_sell("SOLUSDT", Decimal("0.1"), Decimal("102"), Decimal("95"), Decimal("94"),
                       parent_client_order_id="BUY", dependencies=placement(journal, legs, payload))
    assert journal.partial_protection_exit_quantity("BUY") == Decimal("0.04")
    assert journal.get("BUY").state != "CLOSED"
    assert not journal.get("BUY").metadata.get("exact_lifecycle")


@pytest.mark.parametrize("error", [requests.Timeout, RuntimeError])
def test_placement_read_failure_preserves_live_list(evidence, error):
    journal, legs, payload = evidence
    calls = []
    def unavailable(*_):
        calls.append(True)
        raise error("synthetic read failure")
    with pytest.raises(error):
        place_oco_sell("SOLUSDT", Decimal("0.1"), Decimal("102"), Decimal("95"), Decimal("94"),
                       parent_client_order_id="BUY", dependencies=placement(journal, legs, payload, unavailable))
    assert calls == [True]
    assert journal.get("BUY").state == "PROTECTED"


@pytest.mark.parametrize("field,value", [("orderId", 999), ("symbol", "ETHUSDT"),
                                         ("orderListId", 888), ("clientOrderId", "OTHER")])
def test_worker_rejects_foreign_oco_leg(evidence, field, value):
    _, legs, payload = evidence
    legs[0][field] = value
    with pytest.raises(RuntimeError, match="identity"):
        executor_recovery.verify_oco_legs("SOLUSDT", payload, signed_request=lambda *a: legs[0])


def test_worker_wrong_market_cannot_fall_back():
    calls = []
    def public(*args):
        calls.append(args)
        return dict(symbol="ETHUSDT", price="3000", private="do-not-leak")
    with pytest.raises(ValueError) as caught:
        executor_market.get_price_decimal("SOLUSDT", public_get=public, logger=lambda _: None)
    assert len(calls) == 1
    assert "do-not-leak" not in str(caught.value)


@pytest.mark.parametrize("payload", [None, {}, {"balances": None},
    {"balances": [dict(asset="USDT", free="1", locked="0")] * 2}])
def test_account_rejects_missing_or_duplicate_evidence(payload):
    with pytest.raises(ValueError):
        executor_market.get_balances(signed_request=lambda *a: payload)
    with pytest.raises(ValueError):
        checked_balances(payload)


def test_null_open_orders_is_not_empty():
    with pytest.raises(ValueError):
        executor_recovery.list_open_orders("SOLUSDT", signed_request=lambda *a: None, logger=lambda _: None)


@pytest.mark.parametrize("payload", [None, {}, {"balances": []},
    {"balances": [dict(asset="USDT", free="1", locked="0")] * 2}])
def test_supervisor_uses_shared_response_checks(monkeypatch, payload):
    from ladder_dragon.supervision import runtime
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda *a, **k: payload)
    if payload == {"balances": []}:
        assert runtime.get_balances() == runtime.get_balances_full() == {}
    else:
        with pytest.raises(ValueError):
            runtime.get_balances()
        with pytest.raises(ValueError):
            runtime.get_balances_full()
    with pytest.raises(ValueError):
        runtime.list_open_orders("SOLUSDT")


def test_otoco_uses_documented_oto_contingency(evidence):
    _, _, payload = evidence
    payload["contingencyType"] = "OTO"
    assert checked_list(payload, kind="OTOCO") is payload
    payload["contingencyType"] = "OTOCO"
    with pytest.raises(RuntimeError):
        checked_list(payload, kind="OTOCO")


@pytest.mark.parametrize("status,qty", [("FILLED", "0.1"), ("CANCELED", "0.04")])
def test_single_terminal_exit_cannot_claim_active_protection(evidence, status, qty):
    from dataclasses import replace
    journal, legs, payload = evidence
    journal.mark_failed("LIST", "synthetic replacement")
    journal.prepare(client_order_id="SINGLE", symbol="SOLUSDT", side="SELL", purpose="stop",
                    order_type="STOP_LOSS_LIMIT", quantity="0.1", price="95", parent_client_order_id="BUY")
    order = exit_order(222, "SINGLE", -1, "STOP_LOSS_LIMIT")
    order.update(status=status, executedQty=qty)
    deps = replace(recovery(journal, legs, payload), get_order_by_client_id=lambda *_: order)
    with pytest.raises(RuntimeError, match="residual reconciliation"):
        executor_recovery.recover_existing_protection("BUY", dependencies=deps)
    assert journal.get("SINGLE").state == "PREPARED"


@pytest.mark.parametrize("rows", [[None, {"id": 2}], [{"id": 2}, {"id": 1}], [{"id": True}]])
def test_invalid_fill_identity_sequence_never_advances(tmp_path, rows):
    con = tools_stats.init_db(str(tmp_path / "stats.sqlite3"))
    try:
        executor_stats.poll_mytrades_once("SOLUSDT", connection=con, stats=tools_stats,
            signed_request=lambda *a: rows, commission_value=lambda *a: pytest.fail("invalid sequence"),
            logger=lambda _: None)
        assert tools_stats.get_last_trade_id(con, "SOLUSDT") is None
    finally:
        con.close()


@pytest.mark.parametrize("failed_index", [0, 1])
def test_failed_fill_cannot_be_skipped(tmp_path, failed_index):
    con = tools_stats.init_db(str(tmp_path / "stats.sqlite3"))
    rows = [dict(id=i, isBuyer=True, price="100", qty="0.1", time=1700000000000+i,
                 commission="0", commissionAsset="USDT") for i in (1, 2, 3)]
    rows[failed_index]["price"] = "invalid"
    calls = []
    def signed(method, endpoint, params):
        calls.append(dict(params))
        return [row for row in rows if row["id"] >= params.get("fromId", 0)]
    def poll():
        executor_stats.poll_mytrades_once("SOLUSDT", connection=con, stats=tools_stats,
            signed_request=signed, commission_value=lambda *a: (Decimal("0"), "none"), logger=lambda _: None)
    try:
        poll()
        assert tools_stats.get_last_trade_id(con, "SOLUSDT") == (1 if failed_index else None)
        poll()
        assert calls[-1].get("fromId", 1) == failed_index + 1
        rows[failed_index]["price"] = "100"
        poll()
        assert tools_stats.get_last_trade_id(con, "SOLUSDT") == 3
        assert con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 3
    finally:
        con.close()
