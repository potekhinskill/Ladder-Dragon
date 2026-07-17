import json
from pathlib import Path

import pytest

import ai_plan_runner
import gen_vwap_autotune
import gen_vwap_env
import tools_market


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
