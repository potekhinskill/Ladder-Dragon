import sqlite3

import pytest
import requests

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.journal.retired_protection import (
    candidates, reconcile_retired_protection, retire_canceled,
)
from ladder_dragon.supervision.protection_snapshot import verify_all_live_protection
from tests.execution.test_journal_buy_settlement import seeded, protect
from tests.support.exchange_evidence import exit_order, order_list


def fixture(tmp_path):
    journal, _, _ = seeded(tmp_path)
    protect(journal)
    journal.prepare(client_order_id="new", symbol="SOLUSDT", side="SELL", purpose="oco",
                    order_type="OCO", quantity="0.999", price="102", parent_client_order_id="buy")
    journal.mark_verified_protected(parent_client_order_id="buy", protection_client_order_id="new",
                                   order_list_id=220, legs=[
                                       dict(orderId=221, clientOrderId="TP-B", type="LIMIT_MAKER"),
                                       dict(orderId=222, clientOrderId="SL-B", type="STOP_LOSS_LIMIT")])
    journal.mark_exact_lifecycle_closed(protection_client_order_id="new", exit_order_id=221,
                                       exit_reason="TP", exit_order=exit_order(221,"TP-B",220,qty="0.999"))
    legs = [dict(exit_order(qty="0.999"), status="CANCELED", executedQty="0", cummulativeQuoteQty="0"),
            dict(exit_order(122,"SL-A",kind="STOP_LOSS_LIMIT",qty="0.999"),
                 status="CANCELED",executedQty="0",cummulativeQuoteQty="0")]
    payload = order_list(120,"oco",legs,status="ALL_DONE")
    return journal, payload, legs


def snapshot(journal):
    with journal._session() as con:
        return {table: [tuple(row) for row in con.execute("SELECT * FROM " + table)]
                for table in ("order_intents", "order_intent_legs", "order_lifecycle_closures",
                              "order_partial_protection_exits")}


def test_cancellation_preserves_exact_closure_and_restart_idempotency(tmp_path):
    journal, payload, legs = fixture(tmp_path)
    before = snapshot(journal)
    parent = journal.get("buy"); replacement = journal.get("new")
    calls = []
    def get(path, params):
        calls.append(path)
        return payload if path == "/api/v3/orderList" else next(l for l in legs if l["orderId"] == params["orderId"])
    # The former protected-BUY loop is empty: this exercises the missing cadence.
    assert journal.protected_buys() == []
    assert verify_all_live_protection(journal, ["SOLUSDT"], open_orders=[],
                                     verify_one=lambda *_: pytest.fail("closed parent"), signed_get=get) == 0
    old = journal.get("oco")
    assert old.state == "CANCELED" and old.metadata["zero_fill_cancel_reconciled"] is True
    assert not old.metadata.get("exact_lifecycle")
    assert journal.get("buy") == parent and journal.get("new") == replacement
    after = snapshot(journal)
    for table in ("order_intent_legs","order_lifecycle_closures","order_partial_protection_exits"):
        assert after[table] == before[table]
    assert calls == ["/api/v3/orderList", "/api/v3/order", "/api/v3/order"]
    restored = OrderJournal(journal.path, venue="mainnet")
    reconcile_retired_protection(restored, lambda *_: pytest.fail("must not refetch retired list"))


@pytest.mark.parametrize("field,value", [
    ("status","NEW"),("status","PARTIALLY_FILLED"),("status","FILLED"),
    ("status","EXPIRED"),("executedQty","0.01"),("executedQty",None),
    ("executedQty","NaN"),("cummulativeQuoteQty","1"),("cummulativeQuoteQty",None),
    ("origQty","0"),("origQty","0.998"),("side","BUY"),("type","LIMIT"),
    ("orderId",999),("orderListId",999),("symbol","ETHUSDT"),("clientOrderId","foreign"),
])
def test_final_writer_rejects_damaged_leg_without_any_write(tmp_path,field,value):
    journal, payload, legs = fixture(tmp_path)
    before = snapshot(journal)
    legs[1][field] = value
    with pytest.raises((ValueError,RuntimeError)):
        retire_canceled(journal,journal.get("oco"),payload,legs)
    assert snapshot(journal) == before


@pytest.mark.parametrize("field,value", [
    ("listStatusType","EXEC_STARTED"),("orderListId",999),
    ("listClientOrderId","other"),("symbol","ETHUSDT"),("contingencyType","OTO"),
    ("orders",[]),
])
def test_list_identity_and_terminal_state_required(tmp_path,field,value):
    journal,payload,legs=fixture(tmp_path); before=snapshot(journal)
    payload[field]=value
    with pytest.raises((ValueError,RuntimeError)):
        retire_canceled(journal,journal.get("oco"),payload,legs)
    assert snapshot(journal)==before


def test_timeout_never_mutates_or_cancels(tmp_path):
    journal,_,_=fixture(tmp_path);before=snapshot(journal)
    def fail(*_):
        raise requests.Timeout("synthetic")
    with pytest.raises(requests.Timeout):
        reconcile_retired_protection(journal,fail)
    assert snapshot(journal)==before


@pytest.mark.parametrize("change", ["parent", "child", "closure", "leg"])
def test_revalidate_durable_state_at_writer(tmp_path,change):
    journal,payload,legs=fixture(tmp_path); observed=journal.get("oco")
    if change=="parent":
        journal.mark_protection_pending("buy")
    elif change=="child":
        journal.update_metadata("oco",{"synthetic_changed":True})
    else:
        with journal._session(write=True) as con:
            con.execute("DELETE FROM order_lifecycle_closures" if change=="closure" else
                        "DELETE FROM order_intent_legs WHERE protection_client_order_id='oco'")
    before=snapshot(journal)
    with pytest.raises(RuntimeError):
        retire_canceled(journal,observed,payload,legs)
    assert snapshot(journal)==before


def test_write_failure_rolls_back(tmp_path,monkeypatch):
    journal,payload,legs=fixture(tmp_path);before=snapshot(journal)
    update=journal._update_row
    def fail(con,*args):
        update(con,*args)
        raise sqlite3.OperationalError("synthetic failure after update")
    monkeypatch.setattr(journal,"_update_row",fail)
    with pytest.raises(sqlite3.OperationalError):
        retire_canceled(journal,journal.get("oco"),payload,legs)
    assert snapshot(journal)==before


def test_capacity_blocks_before_reads_or_writes(tmp_path):
    journal,_,_=fixture(tmp_path)
    for index in range(16):
        child=f"extra-{index}"
        journal.prepare(client_order_id=child,symbol="SOLUSDT",side="SELL",purpose="oco",
                        order_type="OCO",quantity="0.999",price="102",parent_client_order_id="buy")
        journal._update(child,state="PROTECTED")
    before=snapshot(journal)
    with pytest.raises(RuntimeError,match="capacity"):
        reconcile_retired_protection(journal,lambda *_:pytest.fail("capacity before network"))
    assert snapshot(journal)==before


def test_supervisor_adapter_supplies_fresh_signed_reads():
    import ast
    from pathlib import Path
    tree=ast.parse((Path(__file__).resolve().parents[2]/"ladder_dragon/supervision/runtime.py").read_text())
    wrapper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_verify_all_live_protection")
    calls=[n for n in ast.walk(wrapper) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
           and n.func.id=="_verify_all_live_protection_service"]
    assert len(calls)==1
    assert any(k.arg=="signed_get" and ast.unparse(k.value)=="TM._signed_get" for k in calls[0].keywords)
