from decimal import Decimal as D
from types import SimpleNamespace
import runpy

import pytest
import requests

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.protection.buy_inventory import settle_inventory
from ladder_dragon.execution.journal.buy_inventory import SETTLEMENT_KEY


def entry(tmp_path, *, quantity="1", quote="100", fee="0.001", asset="SOL"):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(client_order_id="buy", symbol="SOLUSDT", side="BUY", purpose="ladder",
                    order_type="LIMIT", quantity=quantity, price="100")
    order = dict(symbol="SOLUSDT", side="BUY", orderId=42, origQty=quantity,
                 executedQty=quantity, cummulativeQuoteQty=quote, status="FILLED")
    journal.record_exchange_order("buy", order)
    fills = [dict(symbol="SOLUSDT", side="BUY", orderId=42, id=0, isBuyer=True,
                  qty=quantity, price="100", quoteQty=quote, commission=fee, commissionAsset=asset)]
    return journal, order, fills


@pytest.mark.parametrize("asset, expected", [("SOL", "0.999"), ("USDT", "1"), ("BNB", "1")])
def test_runtime_sizes_only_order_net_inventory(tmp_path, asset, expected):
    h = runpy.run_path("tests/test_executor_protection.py")
    journal, order, fills = entry(tmp_path, asset=asset)
    quantities, calls = [], []
    deps = h["dependencies"](
        journal=lambda: journal, get_order=lambda *args: order,
        settle_inventory=lambda j, p, o: settle_inventory(j, p, o, read_fills=lambda *args: fills),
        get_balances=lambda: {"SOL": {"free": "50", "locked": "0"}},
        place_oco_sell=lambda symbol, qty, *args, **kwargs: quantities.append(qty) or {"orderListId": 77},
        halt=lambda *args, **kwargs: calls.append(args),
    )
    assert h["protect_filled_buys"](
        "SOLUSDT", [42], [90, 110], config=h["config"](), panic_active=False,
        breakeven_enabled=False, state_store=h["state_store"](tmp_path), dependencies=deps,
    ) == []
    assert quantities == [D(expected)] and calls == []


@pytest.mark.parametrize("failure", ["missing", "foreign", "timeout", "dust"])
def test_bad_settlement_or_dust_halts_without_protection_mutation(tmp_path, failure):
    h = runpy.run_path("tests/test_executor_protection.py")
    journal, order, fills = entry(tmp_path, fee="0.0001" if failure == "dust" else "0.001")
    def read(*args):
        if failure == "timeout":
            raise requests.Timeout("private-provider-text")
        if failure == "missing":
            return []
        return [dict(fills[0], symbol="ETHUSDT")] if failure == "foreign" else fills
    def forbidden(*args, **kwargs):
        pytest.fail("uncertain inventory must not mutate protection")
    halts = []
    deps = h["dependencies"](
        journal=lambda: journal, get_order=lambda *args: order,
        settle_inventory=lambda j, p, o: settle_inventory(j, p, o, read_fills=read),
        recover_existing_protection=lambda _: False,
        place_oco_sell=forbidden, place_market_order=forbidden, cancel_oco=forbidden,
        halt=lambda *args, **kwargs: halts.append(str(args)),
    )
    assert h["protect_filled_buys"](
        "SOLUSDT", [42], [90, 110], config=h["config"](), panic_active=False,
        breakeven_enabled=False, state_store=h["state_store"](tmp_path), dependencies=deps,
    ) == [42]
    assert halts and "private-provider-text" not in str(halts)
    assert journal.get("buy").state != "CLOSED"


def test_restart_revalidates_cached_evidence_without_network(tmp_path):
    journal, order, fills = entry(tmp_path)
    assert settle_inventory(journal, "buy", order, read_fills=lambda *args: fills) == D("0.999")
    restored = OrderJournal(journal.path, venue="mainnet")
    def forbidden(*args):
        pytest.fail("durable settlement must not query again")
    assert settle_inventory(restored, "buy", order, read_fills=forbidden) == D("0.999")
    with pytest.raises(ValueError):
        settle_inventory(restored, "buy", dict(order, orderId=99), read_fills=forbidden)


def test_paginated_fills_prove_terminal_sum(tmp_path):
    journal, order, fills = entry(tmp_path, quantity="1.001", quote="100.1")
    rows = [dict(fills[0], id=i, qty="0.001", quoteQty="0.1", commission="0.000001") for i in range(1001)]
    cursors = []
    def read(symbol, order_id, cursor):
        assert (symbol, order_id) == ("SOLUSDT", 42)
        cursors.append(cursor)
        return rows[cursor:cursor + 1000]
    assert settle_inventory(journal, "buy", order, read_fills=read) == D("0.999999")
    assert cursors == [0, 1000]


@pytest.mark.parametrize("page", [None, {}, [{"id": True}], [{"id": 2}, {"id": 1}], [{"id": 1}, {"id": 1}]])
def test_malformed_page_never_persists_settlement(tmp_path, page):
    journal, order, _ = entry(tmp_path)
    with pytest.raises(RuntimeError):
        settle_inventory(journal, "buy", order, read_fills=lambda *args: page)
    assert SETTLEMENT_KEY not in (journal.get("buy").metadata or {})


def test_worker_factory_wires_bounded_order_specific_reader(tmp_path, monkeypatch):
    from tests.support.module_loaders import load_worker
    worker = load_worker()
    journal, order, fills = entry(tmp_path)
    calls = []
    def signed(*args, **kwargs):
        calls.append((args, kwargs))
        return fills
    monkeypatch.setattr(worker, "TRANSPORT", SimpleNamespace(signed_request=signed))
    assert worker._protection_dependencies().settle_inventory(journal, "buy", order) == D("0.999")
    assert calls == [(("GET", "/api/v3/myTrades", {"symbol": "SOLUSDT", "orderId": 42,
                      "fromId": 0, "limit": 1000}), {"maximum_response_bytes": 2 * 1024 * 1024})]


def test_partial_exit_replacement_uses_net_residual(tmp_path):
    h = runpy.run_path("tests/test_executor_protection.py")
    journal, order, fills = entry(tmp_path)
    settle_inventory(journal, "buy", order, read_fills=lambda *args: fills)
    runpy.run_path("tests/execution/test_journal_buy_settlement.py")["protect"](journal)
    journal.record_partial_protection_exit(protection_client_order_id="oco", exit_order_id=121,
                                          exit_reason="TP", executed_qty="0.4", terminal_status="CANCELED")
    quantities = []
    deps = h["dependencies"](
        journal=lambda: journal, get_order=lambda *args: order,
        settle_inventory=lambda j, p, o: settle_inventory(j, p, o, read_fills=lambda *args: pytest.fail("unexpected read")),
        place_oco_sell=lambda symbol, qty, *args, **kwargs: quantities.append(qty) or {"orderListId": 78},
    )
    assert h["protect_filled_buys"](
        "SOLUSDT", [42], [90, 110], config=h["config"](), panic_active=False,
        breakeven_enabled=False, state_store=h["state_store"](tmp_path), dependencies=deps,
    ) == []
    assert quantities == [D("0.599")]


def test_page_capacity_does_not_attest_truncated_fill_history(tmp_path):
    journal, order, fills = entry(tmp_path, quantity="2", quote="200")
    calls = []
    def read(symbol, order_id, cursor):
        calls.append(cursor)
        return [dict(fills[0], id=i, qty="0.0001", quoteQty="0.01", commission="0")
                for i in range(cursor, cursor + 1000)]
    with pytest.raises(ValueError, match="cover"):
        settle_inventory(journal, "buy", order, read_fills=read)
    assert len(calls) == 10
    assert SETTLEMENT_KEY not in (journal.get("buy").metadata or {})
