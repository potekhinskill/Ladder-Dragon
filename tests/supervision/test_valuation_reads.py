"""Parallel fallback reads preserve exact policy order and global capacity."""

from decimal import Decimal
import threading
import time

import pytest

from ladder_dragon.supervision import runtime
from ladder_dragon.supervision.valuation_reads import ValuationReads
from tests.supervision.test_snapshot_tickers import snapshot_runtime


def missing():
    return runtime.TM.BinanceHttpError(status=400, code=-1121)


def test_serial_setting_preserves_short_circuit():
    reads = ValuationReads(1)
    calls = []
    try:
        for value in reads.routes([1, 2, 3], lambda item: calls.append(item) or item):
            if value == 1:
                break
    finally:
        reads.close()
    assert calls == [1]


def test_slower_first_route_wins_and_prices_are_not_reused(monkeypatch, snapshot_runtime, capsys):
    later_finished = threading.Event()
    price = [Decimal("2.123456789123456789")]
    calls = []
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {
        "AAA": {"free": "3", "locked": "0"}})

    def read(symbol):
        calls.append(symbol)
        if symbol == "SOLUSDT":
            return Decimal("75")
        if symbol == "AAAUSDC":
            assert later_finished.wait(2), "fallback routes did not overlap"
            return price[0]
        if symbol == "AAAFDUSD":
            later_finished.set()
            return Decimal("100")
        raise missing()

    monkeypatch.setattr(runtime, "get_last_price_decimal", read)
    for value in ("2.123456789123456789", "3.123456789123456789"):
        price[0] = Decimal(value)
        later_finished.clear()
        result, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
        assert result.equity_usdt == Decimal("3") * price[0] * Decimal("0.998")
    assert calls.count("AAAUSDC") == calls.count("AAAFDUSD") == 2
    assert "synthetic-private-marker" not in str(capsys.readouterr())


@pytest.mark.parametrize("depth", [False, True])
@pytest.mark.parametrize("capacity", [1, 2, 4])
def test_snapshot_global_capacity_includes_depth_and_bridge(monkeypatch, snapshot_runtime, depth, capacity):
    monkeypatch.setenv("RISK_CONVERSION_DEPTH_REQUIRED", str(int(depth)))
    monkeypatch.setenv("RISK_PUBLIC_READ_CONCURRENCY", str(capacity))
    monkeypatch.setattr(runtime, "get_balances_full", lambda: {
        asset: {"free": "1", "locked": "0"} for asset in ("AAA", "BBB", "CCC")})
    lock = threading.Lock()
    active = peak = 0

    def network(value):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.005)
            return value
        finally:
            with lock:
                active -= 1

    def read(symbol):
        value = network(Decimal("2"))
        if symbol in {"SOLUSDT", "BTCUSDT", "ETHUSDT"} or symbol.endswith(("BTC", "ETH")):
            return value
        raise missing()

    def book(endpoint, params):
        assert endpoint == "/api/v3/depth"
        return network({"bids": [["2", "100"]], "asks": [["3", "100"]]})

    def phase(name, values):
        if name == "valuation_routes":
            assert active == 0

    monkeypatch.setattr(runtime, "get_last_price_decimal", read)
    monkeypatch.setattr(runtime.TM, "_public_get", book)
    monkeypatch.setattr(runtime, "_record_risk_startup_phase", phase)
    result, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], snapshot_runtime)
    assert result.equity_usdt > 0
    assert active == 0 and 1 <= peak <= capacity
    if capacity > 1:
        assert peak > 1


def test_failure_drains_other_reads_and_does_not_print_errors(capsys):
    started = threading.Event()
    finished = threading.Event()
    reads = ValuationReads(2)

    def read(item):
        if item == 0:
            assert started.wait(2)
            raise ValueError("synthetic-private-marker")
        started.set()
        time.sleep(0.02)
        finished.set()

    with pytest.raises(ValueError, match="synthetic-private-marker"):
        try:
            reads.routes([0, 1], read)
        finally:
            reads.close()
    assert finished.is_set()
    assert "synthetic-private-marker" not in str(capsys.readouterr())
