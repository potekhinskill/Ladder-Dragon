import argparse

import pytest

from binance_transport import BinanceTransport
from executor_config import build_executor_parser, validate_executor_args
from strategy_math import (
    adx_from_klines,
    atr_from_klines,
    ema_series,
    ema_value,
    geometric_ladder,
    panic_triggered,
    shift_buy_levels,
    split_ladder,
)
from supervisor_config import build_supervisor_parser, validate_supervisor_args


def test_executor_config_owns_parser_and_strict_validation(monkeypatch):
    parser = build_executor_parser()
    args = parser.parse_args([
        "--symbol", "solusdt",
        "--ladder-prices", "90,110",
    ])
    validated = validate_executor_args(parser, args)
    assert validated.symbol == "SOLUSDT"

    monkeypatch.delenv("BOT_LIVE_CONFIRMED", raising=False)
    with pytest.raises(SystemExit) as exc:
        validate_executor_args(parser, argparse.Namespace(**{**vars(args), "live": True}))
    assert exc.value.code == 2


def test_supervisor_config_owns_parser_and_validation(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text("", encoding="utf-8")
    parser = build_supervisor_parser()
    args = parser.parse_args([
        "--base-script", str(worker),
        "--symbols", "SOLUSDT,ETHUSDT",
    ])
    assert validate_supervisor_args(parser, args) == ["SOLUSDT", "ETHUSDT"]


def test_shared_strategy_math_has_no_runtime_dependencies():
    ladder = geometric_ladder(100.0, -0.5, -5.0, 5.0, 3)
    buys, sells = split_ladder(100.0, ladder)
    assert len(buys) == len(sells) == 3
    assert all(price < 100 for price in buys)
    assert all(price > 100 for price in sells)
    assert shift_buy_levels(ladder, 100.0, 0.10) == [
        *(price * 0.9 for price in buys),
        *sells,
    ]
    assert ema_value([1.0, 2.0, 3.0], 2) == pytest.approx(2.5555555556)
    assert len(ema_series([1.0, 2.0, 3.0], 2)) == 3
    assert panic_triggered(90.0, 100.0, 2.0, 100.0, 0.05, 2.0)


def test_indicator_math_handles_recorded_candle_shape():
    candles = [
        [index, "0", str(100 + index), str(98 + index), str(99 + index), "10"]
        for index in range(20)
    ]
    assert atr_from_klines(candles, period=5) > 0
    assert adx_from_klines(candles, length=5) >= 0


def test_binance_transport_blocks_mutations_before_network():
    class NoNetworkSession:
        def request(self, *args, **kwargs):
            raise AssertionError("network must not be reached in DRY mode")

    transport = BinanceTransport(
        NoNetworkSession(),
        base_url=lambda: "https://testnet.binance.vision",
        api_key=lambda: "key",
        api_secret=lambda: "secret",
        live=lambda: False,
        recv_window=lambda: 5000,
        logger=lambda message: None,
    )
    with pytest.raises(RuntimeError, match="DRY mode blocked"):
        transport.signed_request("DELETE", "/api/v3/order", {"symbol": "SOLUSDT"})


def test_binance_transport_signs_live_request(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        headers = {}
        text = ""

        @staticmethod
        def json():
            return {"ok": True}

    class Session:
        def request(self, method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return Response()

    monkeypatch.setattr("binance_transport.time.time", lambda: 1_700_000_000.0)
    transport = BinanceTransport(
        Session(),
        base_url=lambda: "https://testnet.binance.vision",
        api_key=lambda: "key",
        api_secret=lambda: "secret",
        live=lambda: True,
        recv_window=lambda: 5000,
        logger=lambda message: None,
    )
    assert transport.signed_request("POST", "/api/v3/order", {"symbol": "SOLUSDT"}) == {"ok": True}
    assert captured["method"] == "POST"
    assert "timestamp=1700000000000" in captured["url"]
    assert "signature=" in captured["url"]
