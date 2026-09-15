"""Keep extracted owners and live resource behavior inside the full harness."""

from decimal import Decimal, getcontext, localcontext
from types import SimpleNamespace
import sqlite3

import pytest

from ladder_dragon.execution.binance_transport import BinanceTransport
from ladder_dragon.execution.journal import metadata
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.protection.buy_inventory import remaining_inventory
from ladder_dragon.execution.worker import runtime as worker
from ladder_dragon.risk import limit_values, risk_manager
from ladder_dragon.strategy.prediction import historical_selection, historical_values


@pytest.mark.parametrize("consumer, name, owner", [
    (OrderJournal, "update_metadata", metadata.update_metadata),
    (risk_manager, "money", limit_values.money),
    (risk_manager.RiskLimits, "status_summary", limit_values.status_summary),
    (historical_selection, "_decimal", historical_values._decimal),
])
def test_consumers_bind_concrete_owner(consumer, name, owner):
    assert getattr(consumer, name) is owner


def test_protection_lot_callback_reads_replaced_resources(monkeypatch):
    first, second = object(), object()
    monkeypatch.setattr(worker, "STATS_CON", first)
    monkeypatch.setattr(worker, "lot_for_order", lambda con, *args: SimpleNamespace(lot_id=1))
    callback = worker._protection_dependencies().lot_id_for_fill
    assert callback("SOLUSDT", Decimal("1"), 42) == 1
    monkeypatch.setattr(worker, "STATS_CON", second)
    def replacement(con, *args):
        assert con is second
        return SimpleNamespace(lot_id=2)
    monkeypatch.setattr(worker, "lot_for_order", replacement)
    assert callback("SOLUSDT", Decimal("1"), 42) == 2
    monkeypatch.setattr(worker, "STATS_CON", None)
    assert callback("SOLUSDT", Decimal("1"), 42) is None


def test_lot_callback_preserves_sqlite_failure_handling(monkeypatch):
    monkeypatch.setattr(worker, "STATS_CON", object())
    def failed(*args):
        raise sqlite3.OperationalError("synthetic")
    monkeypatch.setattr(worker, "lot_for_order", failed)
    callback = worker._protection_dependencies().lot_id_for_fill
    assert callback("SOLUSDT", Decimal("1"), 42) is None


def test_partial_exit_reader_keeps_exact_context():
    def read(parent):
        assert parent == "buy" and getcontext().prec == 512
        return Decimal("0.000000000000000000000000000001")
    with localcontext() as context:
        context.prec = 6
        result = remaining_inventory(SimpleNamespace(partial_protection_exit_quantity=read), "buy", Decimal("1"))
        assert result == Decimal("0.999999999999999999999999999999")
        assert getcontext().prec == 6


@pytest.mark.parametrize("value", ["1.1", "-0.1"])
def test_partial_exit_reader_still_rejects_invalid_exit(value):
    journal = SimpleNamespace(partial_protection_exit_quantity=lambda _: Decimal(value))
    with pytest.raises(RuntimeError):
        remaining_inventory(journal, "buy", Decimal("1"))


@pytest.mark.parametrize("method, limit", [("POST", 10), ("GET", 0), ("GET", True)])
def test_invalid_response_limit_stops_before_credentials(method, limit):
    def forbidden():
        pytest.fail("invalid request reached credentials")
    transport = BinanceTransport(SimpleNamespace(), base_url=forbidden, api_key=forbidden,
                                 api_secret=forbidden, live=lambda: False,
                                 recv_window=lambda: 5000, logger=lambda _: None)
    with pytest.raises(ValueError):
        transport.signed_request(method, "/api/v3/myTrades", maximum_response_bytes=limit)
