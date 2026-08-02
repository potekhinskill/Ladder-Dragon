import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from ladder_dragon.supervision import plan_runner as ai_plan_runner
from bin import gen_vwap_autotune
from bin import gen_vwap_env
from ladder_dragon.execution import tools_market
def test_ladder_has_buy_and_sell_levels():
    levels = ai_plan_runner.build_ladder_pct(100, -5, 3, 12, 0.01)
    assert any(value < 100 for value in levels)
    assert any(value > 100 for value in levels)


def test_plan_runner_validates_symbols_before_network_or_child_processes():
    args = ai_plan_runner.parse_args(
        ["--symbols", "solusdt,ETHUSDT"]
    )
    assert args.symbols == ["SOLUSDT", "ETHUSDT"]

    for invalid in ("-SOLUSDT", "SOL/USDT", "A", "SOLUSDT;echo"):
        with pytest.raises(SystemExit):
            ai_plan_runner.parse_args(["--symbols", invalid])


def test_vwap_discount_adapts_to_regime_and_volatility():
    common = {
        "atr_pct": Decimal("0.01"),
        "up_multiplier": Decimal("0.75"),
        "down_multiplier": Decimal("1.20"),
        "atr_coefficient": Decimal("2"),
        "minimum": Decimal("0"),
        "maximum": Decimal("0.02"),
    }
    assert gen_vwap_env.adaptive_discount(
        Decimal("0.006"), mode="UP", **common
    ) == Decimal("0.0045900")
    assert gen_vwap_env.adaptive_discount(
        Decimal("0.006"), mode="DOWN", **common
    ) == Decimal("0.0073440")


def test_vwap_map_uses_adaptive_discount(monkeypatch):
    args = argparse.Namespace(
        interval="1m", window=120, atr_period=14, ema_fast=20, ema_slow=50,
        dir_eps=0.0005, base_premium=0.003, premium_up_mult=0.75,
        premium_down_mult=1.2, premium_atr_coef=0.0,
        premium_floor=0.0008, premium_ceil=0.006,
        base_discount=Decimal("0.006"), discount_up_mult=Decimal("0.75"),
        discount_down_mult=Decimal("1.20"), discount_atr_coef=Decimal("2"),
        discount_min=Decimal("0"), discount_max=Decimal("0.02"),
        base_scale=1.3, scale_atr_coef=2.0, scale_min=1.0, scale_max=2.5,
    )
    klines = [[0, 0, 101, 99, 100] for _ in range(120)]
    monkeypatch.setattr(gen_vwap_env.TM, "get_klines", lambda *args, **kwargs: klines)
    monkeypatch.setattr(gen_vwap_env, "infer_mode", lambda *args, **kwargs: "DOWN")
    monkeypatch.setattr(gen_vwap_env, "compute_atr", lambda *args, **kwargs: 1.0)

    _, discounts, _ = gen_vwap_env.build_maps(["SOLUSDT"], args)

    assert discounts == {"SOLUSDT": Decimal("0.0073440")}


def test_vwap_discount_autotune_uses_exact_pnl_and_sample_gate():
    common = {
        "trade_count": 20,
        "minimum_trades": 20,
        "pnl_threshold": Decimal("25"),
        "loss_multiplier": Decimal("1.20"),
        "profit_multiplier": Decimal("0.80"),
        "minimum": Decimal("0"),
        "maximum": Decimal("0.02"),
    }
    assert gen_vwap_autotune.adaptive_discount(
        Decimal("0.006"), pnl=Decimal("-25"), **common
    ) == Decimal("0.00720")
    assert gen_vwap_autotune.adaptive_discount(
        Decimal("0.006"), pnl=Decimal("25"), **common
    ) == Decimal("0.00480")
    common["trade_count"] = 19
    assert gen_vwap_autotune.adaptive_discount(
        Decimal("0.006"), pnl=Decimal("-100"), **common
    ) == Decimal("0.006")
    assert gen_vwap_autotune.decimal_ema(
        "0.006", Decimal("0.00720"), "0.6"
    ) == Decimal("0.006720")


def test_vwap_discount_rejects_invalid_bounds():
    with pytest.raises(ValueError, match="bounds"):
        gen_vwap_env.adaptive_discount(
            "0.006", mode="FLAT", atr_pct="0", up_multiplier="1",
            down_multiplier="1", atr_coefficient="0",
            minimum="0.02", maximum="0.01",
        )


def test_vwap_helpers_are_deterministic():
    assert gen_vwap_env.ema([1, 2, 3, 4], 3) == pytest.approx(3.125)


def test_vwap_generator_treats_closed_stdout_as_normal_shutdown(monkeypatch):
    def closed_stdout(*args, **kwargs):
        raise BrokenPipeError

    monkeypatch.setattr("builtins.print", closed_stdout)

    assert gen_vwap_env.emit_lines(["BUY_VWAP_PREMIUM_MAP=SOLUSDT:0.003000"]) is False


def test_vwap_update_uses_active_interpreter(tmp_path, monkeypatch):
    from bin import update_vwap_env

    commands = []
    monkeypatch.delenv("VWAP_AUTOTUNE", raising=False)
    monkeypatch.setattr(
        update_vwap_env.subprocess,
        "check_output",
        lambda command, **kwargs: commands.append(command) or "",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "update_vwap_env", "--symbols", "SOLUSDT", "--with-autotune",
            "--out", str(tmp_path / "vwap.env"),
        ],
    )

    update_vwap_env.main()

    assert len(commands) == 2
    assert all(command[0] == sys.executable for command in commands)
    assert all(
        "/home/bot/apps/binance_bot/.venv/bin/python3" not in command
        for command in commands
    )


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
