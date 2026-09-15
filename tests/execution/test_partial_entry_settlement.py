from decimal import Decimal
import runpy

import pytest
import requests

from ladder_dragon.execution.protection.partial_entry import settle_partial_entry


def payload(status="PARTIALLY_FILLED", filled="0.1", **changes):
    return dict(symbol="SOLUSDT", side="BUY", orderId=42, origQty="1",
                executedQty=filled, status=status, **changes)


@pytest.mark.parametrize("final", [payload("CANCELED", "0.2"), payload("FILLED", "1")])
def test_cancel_race_uses_terminal_quantity(final):
    calls = []
    result = settle_partial_entry(
        "SOLUSDT", 42, payload(), cancel=lambda *args: calls.append("cancel"),
        get_order=lambda *args: calls.append("read") or final, logger=lambda _: None,
    )
    assert calls == ["cancel", "read"]
    assert result == final


def test_timeout_is_reconciled_not_assumed_failed():
    def cancel(*args):
        raise requests.Timeout()
    result = settle_partial_entry(
        "SOLUSDT", 42, payload(), cancel=cancel,
        get_order=lambda *args: payload("CANCELED", "0.2"), logger=lambda _: None,
    )
    assert result["executedQty"] == "0.2"


@pytest.mark.parametrize("change", [
    {"status": "PARTIALLY_FILLED"}, {"executedQty": "0.01"},
    {"symbol": "ETHUSDT"}, {"orderId": 99}, {"side": "SELL"},
    {"origQty": "2"}, {"executedQty": "NaN"}, {"status": "FILLED"},
])
def test_uncertain_or_foreign_terminal_result_blocks(change):
    final = payload("CANCELED") | change
    with pytest.raises((ValueError, ArithmeticError)):
        settle_partial_entry("SOLUSDT", 42, payload(), cancel=lambda *args: None,
                             get_order=lambda *args: final, logger=lambda _: None)


def test_runtime_protects_cancel_race_quantity(tmp_path):
    helpers = runpy.run_path("tests/test_executor_protection.py")
    final = payload("CANCELED", "0.2") | {"cummulativeQuoteQty": "20"}
    responses = iter([payload(), final, final])
    cancellations, quantities = [], []
    deps = helpers["dependencies"](
        get_order=lambda *args: next(responses),
        cancel_entry=lambda *args: cancellations.append(args),
        place_oco_sell=lambda symbol, qty, *args, **kw: quantities.append(qty) or {"orderListId": 77},
    )
    remaining = helpers["protect_filled_buys"](
        "SOLUSDT", [42], [90, 110], config=helpers["config"](), panic_active=False,
        breakeven_enabled=False, state_store=helpers["state_store"](tmp_path), dependencies=deps,
    )
    assert remaining == [] and quantities == [Decimal("0.2")]
    assert cancellations == [("SOLUSDT", 42)]


def test_runtime_unknown_cancel_keeps_watch_and_halts(tmp_path):
    helpers = runpy.run_path("tests/test_executor_protection.py")
    halts = []
    def forbidden(*args, **kwargs):
        raise AssertionError("unsettled BUY cannot create protection")
    deps = helpers["dependencies"](
        get_order=lambda *args: payload(), cancel_entry=lambda *args: None,
        halt=lambda *args, **kw: halts.append(args), place_oco_sell=forbidden,
    )
    remaining = helpers["protect_filled_buys"](
        "SOLUSDT", [42], [90, 110], config=helpers["config"](), panic_active=False,
        breakeven_enabled=False, state_store=helpers["state_store"](tmp_path), dependencies=deps,
    )
    assert remaining == [42] and len(halts) == 1


def test_runtime_restart_recovers_protection_without_another_cancel(tmp_path):
    from types import SimpleNamespace
    helpers = runpy.run_path("tests/test_executor_protection.py")
    def forbidden(*args, **kwargs):
        raise AssertionError("terminal protected entry must not mutate exchange")
    journal = SimpleNamespace(
        get_by_exchange_order_id=lambda _: SimpleNamespace(client_order_id="parent"),
        record_exchange_order=lambda *args: None,
    )
    deps = helpers["dependencies"](
        get_order=lambda *args: payload("CANCELED", "0.2"), journal=lambda: journal,
        cancel_entry=forbidden, place_oco_sell=forbidden,
        recover_existing_protection=lambda _: True,
    )
    for _ in range(2):
        assert helpers["protect_filled_buys"](
            "SOLUSDT", [42], [90, 110], config=helpers["config"](), panic_active=False,
            breakeven_enabled=False, state_store=helpers["state_store"](tmp_path), dependencies=deps,
        ) == []


def test_replay_cancels_first_partial_and_preserves_cancel_race():
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    event = h["event"]
    x = h["HistoricalExecution"](event(3000), h["HistoricalPolicy"].parse(h["policy"]()), h["context"](), "partial")
    x.process(event(3200), veto=False, panic=False)
    x.process(event(3300, trades=((str(x.entry), "0.1", "SELL"),)), veto=False, panic=False)
    assert x.cancel_reason == "PARTIAL_ENTRY" and x.cancel_effective_ms == 3800
    x.process(event(3800, trades=((str(x.entry), "0.1", "SELL"),)), veto=False, panic=False)
    assert x.entry_qty == Decimal("0.2")
    x.process(event(3801), veto=False, panic=False)
    assert x.phase == "PROTECTED" and x.order("target").quantity == Decimal("0.2")
