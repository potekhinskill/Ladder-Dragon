"""The initial public ticker can overlap preparation without reordering authority."""

from decimal import Decimal
import inspect
import threading
import time

import pytest

from ladder_dragon.supervision import risk_cycle, runtime
from tests.supervision.test_snapshot_tickers import snapshot_runtime


def test_public_ticker_overlaps_account_preparation(monkeypatch, snapshot_runtime):
    ticker_started = threading.Event()
    account_ready = threading.Event()
    calls = []

    def ticker(symbol):
        calls.append(("ticker", symbol))
        ticker_started.set()
        assert account_ready.wait(2)
        return Decimal("75")

    def balances():
        assert ticker_started.wait(2)
        calls.append(("account", None))
        account_ready.set()
        return {"USDT": {"free": "100", "locked": "0"}}

    monkeypatch.setattr(runtime, "get_initial_last_price_decimal", ticker)
    monkeypatch.setattr(runtime, "get_balances_full", balances)
    result, _, prices = runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)

    assert result.equity_usdt == 100
    assert prices == {"SOLUSDT": Decimal("75")}
    assert calls == [("ticker", "SOLUSDT"), ("account", None)]


def test_fill_failure_drains_public_ticker_without_account_or_order_reads(
    monkeypatch, snapshot_runtime, capsys,
):
    ticker_started = threading.Event()
    ticker_finished = threading.Event()
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "1")

    def ticker(_symbol):
        ticker_started.set()
        time.sleep(0.03)
        ticker_finished.set()
        return Decimal("75")

    def fill_failure(_symbols):
        assert ticker_started.wait(2)
        raise RuntimeError("synthetic-private-marker")

    monkeypatch.setattr(runtime, "get_initial_last_price_decimal", ticker)
    monkeypatch.setattr(runtime, "_sync_recent_account_fills", fill_failure)
    monkeypatch.setattr(runtime, "get_balances_full",
                        lambda: pytest.fail("account read followed fill failure"))
    monkeypatch.setattr(runtime.TM, "_signed_get",
                        lambda *_args: pytest.fail("order read followed fill failure"))

    with pytest.raises(RuntimeError, match="synthetic-private-marker"):
        runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
    assert ticker_finished.is_set()
    assert "synthetic-private-marker" not in str(capsys.readouterr())


def test_ticker_failure_surfaces_after_account_and_before_orders(
    monkeypatch, snapshot_runtime,
):
    account_ready = threading.Event()

    def ticker(_symbol):
        assert account_ready.wait(2)
        raise RuntimeError("public ticker failed")

    def balances():
        account_ready.set()
        return {"USDT": {"free": "100", "locked": "0"}}

    monkeypatch.setattr(runtime, "get_initial_last_price_decimal", ticker)
    monkeypatch.setattr(runtime, "get_balances_full", balances)
    monkeypatch.setattr(runtime.TM, "_signed_get",
                        lambda *_args: pytest.fail("orders followed ticker failure"))

    with pytest.raises(RuntimeError, match="public ticker failed"):
        runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)


def test_signed_reads_and_reconciliation_are_not_submitted_to_executor():
    source = inspect.getsource(risk_cycle.build_risk_snapshot)
    submitted = source[source.index("ticker_future = executor.submit"):
                       source.index("configured_prices = ticker_future.result()")]
    assert "get_initial_last_price_decimal" in submitted
    assert "sync_recent_account_fills" not in submitted.split("\n", 4)[0]
    assert "get_balances_full" not in submitted.split("\n", 4)[0]
    assert '"/api/v3/openOrders"' not in submitted
