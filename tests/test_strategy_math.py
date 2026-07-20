import json
from decimal import Decimal
from pathlib import Path

import pytest

from bin import ai_plan_runner
from bin import gen_vwap_autotune
from bin import gen_vwap_env
from ladder_dragon.execution import tools_market
def test_ladder_has_buy_and_sell_levels():
    levels = ai_plan_runner.build_ladder_pct(100, -5, 3, 12, 0.01)
    assert any(value < 100 for value in levels)
    assert any(value > 100 for value in levels)


def test_fifo_pnl_handles_partial_sell_and_fee():
    rows = [
        ("BUY", 100.0, 1.0, 0.1),
        ("SELL", 110.0, 0.4, 0.1),
    ]
    assert gen_vwap_autotune.compute_fifo_pnl(rows) == pytest.approx(3.86)


def test_vwap_helpers_are_deterministic():
    assert gen_vwap_env.ema([1, 2, 3, 4], 3) == pytest.approx(3.125)


def test_vwap_generator_treats_closed_stdout_as_normal_shutdown(monkeypatch):
    def closed_stdout(*args, **kwargs):
        raise BrokenPipeError

    monkeypatch.setattr("builtins.print", closed_stdout)

    assert gen_vwap_env.emit_lines(["BUY_VWAP_PREMIUM_MAP=SOLUSDT:0.003000"]) is False


def test_recorded_exchange_filters(monkeypatch):
    fixture = Path("tests/fixtures/binance/exchange_info_solusdt.json")
    payload = json.loads(fixture.read_text())
    monkeypatch.setattr(tools_market, "_public_get", lambda *args, **kwargs: payload)
    tools_market._exchange_cache = {}
    tools_market._exchange_cache_ts = {}
    result = tools_market.get_symbol_filters("SOLUSDT")
    assert result["tickSize"] == pytest.approx(0.01)
    assert result["stepSize"] == pytest.approx(0.001)
    assert result["minNotional"] == pytest.approx(5.0)
    assert result["tickSizeExact"] == "0.01000000"
    assert result["stepSizeExact"] == "0.00100000"
    assert result["minNotionalExact"] == "5.00000000"


def test_order_normalization_uses_exact_filter_strings(monkeypatch):
    filters = {
        "stepSize": 1e-08,
        "tickSize": 1e-08,
        "minQty": 1e-08,
        "minNotional": 0.00000001,
        "stepSizeExact": "0.00000001",
        "tickSizeExact": "0.00000001",
        "minQtyExact": "0.00000001",
        "minNotionalExact": "0.00000001",
    }
    monkeypatch.setattr(tools_market, "get_symbol_filters", lambda _symbol: filters)

    qty, price = tools_market.round_qty_price(
        "TINYUSDT",
        Decimal("1.234567899"),
        Decimal("0.123456789"),
        side="BUY",
    )

    assert qty == "1.23456789"
    assert price == "0.12345678"
