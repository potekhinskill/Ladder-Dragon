"""Exercise provider corruption through acceptance and durable retry boundaries."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
import sqlite3

import pytest
import requests

from ladder_dragon.execution import executor_recovery, executor_stats, tools_stats
from ladder_dragon.execution.open_order_snapshot import checked_open_orders
from ladder_dragon.execution.orders.runtime import place_limit_order, place_market_order
from ladder_dragon.execution.orders.reconciliation import UncertainOrderSubmission
from ladder_dragon.execution.worker.stats_sync import sync_account_trades
from tests.execution.test_shared_exchange_evidence import evidence, recovery, placement
from tests.support.exchange_evidence import exit_order


@pytest.mark.parametrize("field,value", [("side", "BUY"), ("type", "LIMIT"), ("type", "TAKE_PROFIT_LIMIT")])
def test_single_stop_purpose(evidence, field, value):
    journal, legs, payload = evidence
    journal.mark_failed("LIST", "synthetic replacement")
    journal.prepare(client_order_id="SINGLE", symbol="SOLUSDT", side="SELL", purpose="stop",
                    order_type="STOP_LOSS_LIMIT", quantity="0.1", price="95", parent_client_order_id="BUY")
    row = exit_order(222, "SINGLE", -1, "STOP_LOSS_LIMIT")
    row.update(status="NEW", executedQty="0")
    deps = replace(recovery(journal, legs, payload), get_order_by_client_id=lambda *_: row)
    row[field] = value
    with pytest.raises(RuntimeError, match="single protection"):
        executor_recovery.recover_existing_protection("BUY", dependencies=deps)
    assert journal.get("SINGLE").state == "PREPARED"
    row.update(side="SELL", type="STOP_LOSS_LIMIT")
    assert executor_recovery.recover_existing_protection("BUY", dependencies=deps)


@pytest.mark.parametrize("market", [False, True])
@pytest.mark.parametrize("field,value", [("symbol", "ETHUSDT"), ("side", "SELL"),
    ("clientOrderId", "private-provider-marker"), ("type", "STOP_LOSS_LIMIT"),
    ("origQty", "0.2"), ("executedQty", "0.04"), ("orderId", True), ("status", None)])
def test_bad_ack_stops_submission(evidence, market, field, value, capsys):
    journal, legs, payload = evidence
    calls, halts = [], []
    def post(method, endpoint, params):
        calls.append(params)
        row = dict(symbol=params["symbol"], side=params["side"], type=params["type"],
                   clientOrderId=params["newClientOrderId"], orderId=900, orderListId=-1,
                   origQty=params["quantity"], price=params.get("price", "0"), executedQty="0", status="NEW")
        row[field] = value
        return row
    deps = replace(placement(journal, legs, payload), signed_request=post,
                   halt=lambda *a, **k: halts.append(a))
    with pytest.raises(UncertainOrderSubmission) as caught:
        if market:
            place_market_order("SOLUSDT", "BUY", Decimal("0.1"), dependencies=deps)
        else:
            place_limit_order("BUY", "SOLUSDT", Decimal("0.1"), Decimal("100"), purpose="audit", dependencies=deps)
    assert len(calls) == 1 and halts
    assert journal.get(calls[0]["newClientOrderId"]).state == "UNKNOWN"
    assert "private-provider-marker" not in str(caught.value) + str(halts) + str(capsys.readouterr())


def trade_row(identity=1):
    return dict(symbol="SOLUSDT", id=identity, orderId=5, isBuyer=True, price="100", qty="0.1",
                time=1700000000000 + identity, commission="0", commissionAsset="USDT")


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("field,value", [("symbol", "ETHUSDT"), ("isBuyer", "false"),
    ("isBuyer", None), ("commission", None), ("commissionAsset", None), ("orderId", True),
    ("commission", "NaN"), ("commission", "-1"), ("time", 0)])
def test_bad_fill_keeps_cursor(tmp_path, strict, field, value):
    con = tools_stats.init_db(str(tmp_path / "stats.sqlite3"))
    rows = [trade_row(1), trade_row(2), trade_row(3)]
    rows[1][field] = value
    if value is None:
        rows[1].pop(field)
    def poll():
        executor_stats.poll_mytrades_once("SOLUSDT", connection=con, stats=tools_stats,
            signed_request=lambda *a: rows, commission_value=lambda *a: (Decimal("0"), "none"),
            logger=lambda _: None, strict=strict)
    try:
        if strict:
            with pytest.raises(RuntimeError):
                poll()
        else:
            poll()
        # Strict failure can retain the old cursor; neither mode can cross row 2.
        assert tools_stats.get_last_trade_id(con, "SOLUSDT") in (None, 1)
        assert con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
    finally:
        con.close()


def test_lot_failure_retries_after_reload(tmp_path):
    path = str(tmp_path / "stats.sqlite3")
    row = trade_row()
    con = tools_stats.init_db(path)
    calls = []
    failed = [True]
    def sync(connection, fill):
        calls.append(fill["trade_id"])
        if failed[0]:
            raise sqlite3.OperationalError("synthetic failure")
        from ladder_dragon.execution.inventory_lots import sync_exchange_fill
        sync_exchange_fill(connection, fill)
    from ladder_dragon.execution.inventory_lots import ensure_schema as ensure_lots_schema
    runtime = dict(Decimal=Decimal, STATS_CON=con, STATS_DB=path, STATS_ENABLE=True, TOOLS_STATS=tools_stats,
        _commission_quote_value=lambda *a: (Decimal("0"), "none"), _order_journal=lambda: None,
        _signed_request=lambda *a: [row] if a[2].get("fromId", 0) <= 1 else [],
        _stats_init_if_needed=lambda: None, dbg=lambda _: None, ensure_lots_schema=ensure_lots_schema,
        get_order=lambda *_: None, log=lambda _: None, os=SimpleNamespace(getenv=lambda *a: ""),
        poll_mytrades_once=executor_stats.poll_mytrades_once, requests=requests, sqlite3=sqlite3, sync_exchange_fill=sync)
    sync_account_trades("SOLUSDT", runtime=runtime)
    assert tools_stats.get_last_trade_id(con, "SOLUSDT") is None
    con.close()
    con = tools_stats.init_db(path)
    runtime["STATS_CON"] = con
    failed[0] = False
    try:
        sync_account_trades("SOLUSDT", runtime=runtime)
        sync_account_trades("SOLUSDT", runtime=runtime)
        assert calls == [1, 1]
        assert tools_stats.get_last_trade_id(con, "SOLUSDT") == 1
        assert con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
    finally:
        con.close()


@pytest.mark.parametrize("symbol", ["\u6d4b\u8bd5USDT", "\uff11\uff12\uff13\uff14\uff15\uff16"])
def test_utf8_orders_keep_exact_identity(symbol):
    row = dict(symbol=symbol, orderId=1, orderListId=-1, clientOrderId="TEST", side="SELL",
               status="NEW", type="LIMIT", price="100", origQty="0.1", executedQty="0")
    assert checked_open_orders([row], symbol=symbol) == [row]
    with pytest.raises(ValueError):
        checked_open_orders([row], symbol="SOLUSDT")
    for invalid in (symbol + "\n", symbol + "\x00", "", "x" * 129):
        with pytest.raises(ValueError):
            checked_open_orders([dict(row, symbol=invalid)])
