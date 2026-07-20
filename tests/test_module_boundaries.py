import argparse
from decimal import Decimal

import pytest
import requests

from ladder_dragon.execution import tools_market

from ladder_dragon.execution.binance_transport import (
    BinanceNetworkError,
    BinanceResponseError,
    BinanceTransport,
)
from ladder_dragon.execution.executor_config import build_executor_parser, validate_executor_args
from ladder_dragon.execution.executor_market import get_balances, get_price, get_symbol_assets
from ladder_dragon.execution.executor_orders import (
    OrderDependencies, place_limit_order, place_market_order, place_oco_sell,
)
from ladder_dragon.execution.executor_planning import (
    buy_candidates,
    buy_candidates_decimal,
    existing_prices_decimal,
    guarded_sell_levels_decimal,
    guarded_sell_levels,
    plan_buy_order,
    plan_buy_order_decimal,
    plan_sell_order_decimal,
    plan_sell_order,
)
from ladder_dragon.execution.executor_recovery import get_order_by_client_id, verify_oco_legs
from ladder_dragon.execution.executor_runtime import status_due, trading_seconds
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.strategy.strategy_math import (
    adx_from_klines,
    atr_from_klines,
    ema_series,
    ema_value,
    geometric_ladder,
    panic_triggered,
    shift_buy_levels,
    split_ladder,
)
from bin.supervisor_config import build_supervisor_parser, validate_supervisor_args


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
    assert args.oco_fallback == "halt"


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

    monkeypatch.setattr("ladder_dragon.execution.binance_transport.time.time", lambda: 1_700_000_000.0)
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


def test_binance_transport_does_not_retry_or_expose_signed_business_rejection():
    calls = []
    messages = []

    class Response:
        status_code = 400
        headers = {}
        text = ""

        @staticmethod
        def json():
            return {
                "code": -1013,
                "msg": "Filter failure: PERCENT_PRICE_BY_SIDE",
            }

    class Session:
        def request(self, method, url, **kwargs):
            calls.append(url)
            return Response()

    transport = BinanceTransport(
        Session(),
        base_url=lambda: "https://api.binance.com",
        api_key=lambda: "public-key",
        api_secret=lambda: "private-secret",
        live=lambda: True,
        recv_window=lambda: 5000,
        logger=messages.append,
    )

    with pytest.raises(BinanceResponseError) as caught:
        transport.signed_request(
            "POST", "/api/v3/order", {"symbol": "SOLUSDT"}
        )

    assert len(calls) == 1
    assert caught.value.code == -1013
    assert caught.value.endpoint == "/api/v3/order"
    assert "PERCENT_PRICE_BY_SIDE" in str(caught.value)
    assert "signature=" not in str(caught.value)
    assert "private-secret" not in str(caught.value)
    assert all("signature=" not in message for message in messages)


def test_binance_transport_scrubs_signed_url_after_network_retry_exhaustion(
    monkeypatch,
):
    messages = []

    class Session:
        def request(self, method, url, **kwargs):
            raise requests.ConnectionError(
                f"connection lost for {url}&private_marker=must-not-leak"
            )

    monkeypatch.setattr(
        "ladder_dragon.execution.binance_transport.time.sleep", lambda _: None
    )
    transport = BinanceTransport(
        Session(),
        base_url=lambda: "https://api.binance.com",
        api_key=lambda: "public-key",
        api_secret=lambda: "private-secret",
        live=lambda: True,
        recv_window=lambda: 5000,
        logger=messages.append,
    )

    with pytest.raises(BinanceNetworkError) as caught:
        transport.signed_request(
            "POST", "/api/v3/order", {"symbol": "SOLUSDT"}
        )

    combined = "\n".join([str(caught.value), *messages])
    assert "signature=" not in combined
    assert "private_marker" not in combined
    assert "private-secret" not in combined
    assert "/api/v3/order" in str(caught.value)


def test_binance_transport_public_throttle_never_logs_query(monkeypatch):
    messages = []

    class Response:
        status_code = 200
        headers = {}
        text = ""

        @staticmethod
        def json():
            return {"code": -1003, "msg": "too many requests"}

    class Session:
        def request(self, method, url, **kwargs):
            return Response()

    monkeypatch.setattr(
        "ladder_dragon.execution.binance_transport.time.sleep", lambda _: None
    )
    transport = BinanceTransport(
        Session(),
        base_url=lambda: "https://api.binance.com",
        api_key=lambda: "key",
        api_secret=lambda: "secret",
        live=lambda: True,
        recv_window=lambda: 5000,
        logger=messages.append,
    )

    with pytest.raises(BinanceResponseError):
        transport.request_with_backoff(
            "GET",
            "https://api.binance.com/api/v3/account?signature=secret-value",
            max_tries=2,
        )

    combined = "\n".join(messages)
    assert "signature=" not in combined
    assert "secret-value" not in combined


def test_executor_market_fallbacks_and_asset_cache():
    calls = []

    def public_get(path, params):
        calls.append(path)
        if path == "/api/v3/ticker/price":
            raise requests.ConnectionError("ticker unavailable")
        if path == "/api/v3/ticker/bookTicker":
            return {"bidPrice": "99", "askPrice": "101"}
        raise AssertionError(path)

    assert get_price("SOLUSDT", public_get=public_get, logger=lambda message: None) == 100
    assert calls == ["/api/v3/ticker/price", "/api/v3/ticker/bookTicker"]

    cache = {}
    assets = get_symbol_assets(
        "SOLUSDT",
        exchange_info=lambda symbol: {
            "symbols": [{"baseAsset": "SOL", "quoteAsset": "USDT"}]
        },
        cache=cache,
    )
    assert assets == ("SOL", "USDT")
    assert cache["SOLUSDT"] == assets

    balances = get_balances(
        signed_request=lambda *args: {
            "balances": [{"asset": "USDT", "free": "10.5", "locked": "1.5"}]
        }
    )
    assert balances["USDT"] == {"free": 10.5, "locked": 1.5}


def test_signed_timestamp_fails_closed_when_exchange_clock_is_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(tools_market, "_time_offset_ms", None)
    monkeypatch.setattr(
        tools_market,
        "_refresh_time_offset",
        lambda: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )
    with pytest.raises(requests.ConnectionError, match="offline"):
        tools_market._timestamp_ms()


def test_executor_recovery_queries_and_verifies_oco():
    class MissingResponse:
        @staticmethod
        def json():
            return {"code": -2013, "msg": "Order does not exist"}

    def missing_order(*args, **kwargs):
        raise requests.HTTPError("missing", response=MissingResponse())

    assert get_order_by_client_id(
        "SOLUSDT", "client", signed_request=missing_order
    ) is None

    def signed(method, path, params):
        order_type = (
            "LIMIT_MAKER" if params["orderId"] == 1 else "STOP_LOSS_LIMIT"
        )
        return {
            "orderId": params["orderId"],
            "side": "SELL",
            "type": order_type,
        }

    legs = verify_oco_legs(
        "SOLUSDT",
        {"orders": [{"orderId": 1}, {"orderId": 2}]},
        signed_request=signed,
    )
    assert {leg["type"] for leg in legs} == {
        "LIMIT_MAKER",
        "STOP_LOSS_LIMIT",
    }


def test_executor_orders_uses_late_bound_dry_gate(tmp_path):
    network_calls = []
    sell_validations = []
    live = {"value": False}
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    dependencies = OrderDependencies(
        live=lambda: live["value"],
        logger=lambda message: None,
        pull_filters=lambda symbol: None,
        round_price=lambda symbol, value: value,
        round_qty=lambda symbol, value: value,
        min_qty=lambda symbol, hint: 0.001,
        min_notional=lambda symbol, price: 5.0,
        format_price=lambda symbol, value: f"{value:.2f}",
        format_qty=lambda symbol, value: f"{value:.3f}",
        journal=lambda: journal,
        signed_request=lambda *args, **kwargs: network_calls.append(args)
        or {"orderId": 7, "status": "NEW", "executedQty": "0"},
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: None,
        validate_limit_sell_prices=lambda symbol, prices: sell_validations.append(
            (symbol, prices)
        ),
    )
    assert place_limit_order(
        "BUY", "SOLUSDT", 0.1, 100.0, dependencies=dependencies
    ) is None
    assert network_calls == []

    live["value"] = True
    result = place_limit_order(
        "SELL", "SOLUSDT", 0.1, 100.0, dependencies=dependencies
    )
    assert result["orderId"] == 7
    assert sell_validations == [("SOLUSDT", ["100.00"])]
    assert len(network_calls) == 1


def test_limit_order_preserves_exact_decimal_payload(tmp_path):
    calls = []
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    dependencies = OrderDependencies(
        live=lambda: True,
        logger=lambda message: None,
        pull_filters=lambda symbol: None,
        round_price=lambda symbol, value: value,
        round_qty=lambda symbol, value: value,
        min_qty=lambda symbol, hint: Decimal("0.000001"),
        min_notional=lambda symbol, price: Decimal("5"),
        format_price=lambda symbol, value: f"{value:.8f}",
        format_qty=lambda symbol, value: f"{value:.6f}",
        journal=lambda: journal,
        signed_request=lambda method, path, params: calls.append(params) or {
            "orderId": 19,
            "status": "NEW",
            "executedQty": "0",
        },
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: None,
        validate_limit_sell_prices=lambda symbol, prices: None,
    )

    result = place_limit_order(
        "SELL",
        "SOLUSDT",
        Decimal("0.123456"),
        Decimal("75.12345678"),
        dependencies=dependencies,
    )

    assert result["orderId"] == 19
    assert calls[0]["quantity"] == "0.123456"
    assert calls[0]["price"] == "75.12345678"


def test_limit_order_rejects_rounded_value_below_minimum_notional(tmp_path):
    calls = []
    dependencies = OrderDependencies(
        live=lambda: True,
        logger=lambda message: None,
        pull_filters=lambda symbol: None,
        round_price=lambda symbol, value: value,
        round_qty=lambda symbol, value: int(value * 10) / 10,
        min_qty=lambda symbol, hint: Decimal("0.1"),
        min_notional=lambda symbol, price: Decimal("5"),
        format_price=lambda symbol, value: f"{value:.2f}",
        format_qty=lambda symbol, value: f"{value:.1f}",
        journal=lambda: None,
        signed_request=lambda *args, **kwargs: calls.append(args),
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: None,
        validate_limit_sell_prices=lambda symbol, prices: None,
    )

    assert place_limit_order(
        "BUY",
        "SOLUSDT",
        Decimal("0.1"),
        Decimal("33"),
        dependencies=dependencies,
    ) is None
    assert calls == []


def test_executor_sell_filter_blocks_before_journal_and_network(tmp_path):
    network_calls = []
    journal = OrderJournal(tmp_path / "orders.sqlite3")

    def reject_price(symbol, prices):
        raise ValueError(f"{symbol} price outside exchange corridor: {prices}")

    dependencies = OrderDependencies(
        live=lambda: True,
        logger=lambda message: None,
        pull_filters=lambda symbol: None,
        round_price=lambda symbol, value: value,
        round_qty=lambda symbol, value: value,
        min_qty=lambda symbol, hint: 0.001,
        min_notional=lambda symbol, price: 5.0,
        format_price=lambda symbol, value: f"{value:.2f}",
        format_qty=lambda symbol, value: f"{value:.3f}",
        journal=lambda: journal,
        signed_request=lambda *args, **kwargs: network_calls.append(args),
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: None,
        validate_limit_sell_prices=reject_price,
    )

    with pytest.raises(ValueError, match="outside exchange corridor"):
        place_limit_order(
            "SELL", "SOLUSDT", 0.1, 150.0, dependencies=dependencies
        )
    assert network_calls == []
    assert journal.nonterminal_orders() == []

    with pytest.raises(ValueError, match="outside exchange corridor"):
        place_oco_sell(
            "SOLUSDT",
            0.1,
            110.0,
            90.0,
            89.0,
            dependencies=dependencies,
            parent_client_order_id="parent-buy",
        )
    assert network_calls == []
    assert journal.nonterminal_orders() == []



def test_executor_market_order_has_live_gate_and_idempotent_payload(tmp_path):
    calls = []
    live = {"value": False}
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    dependencies = OrderDependencies(
        live=lambda: live["value"],
        logger=lambda message: None,
        pull_filters=lambda symbol: None,
        round_price=lambda symbol, value: value,
        round_qty=lambda symbol, value: round(value, 3),
        min_qty=lambda symbol, hint: 0.001,
        min_notional=lambda symbol, price: 5.0,
        format_price=lambda symbol, value: f"{value:.2f}",
        format_qty=lambda symbol, value: f"{value:.3f}",
        journal=lambda: journal,
        signed_request=lambda method, path, params: calls.append((method, path, params))
        or {"orderId": 99, "status": "FILLED", "executedQty": "0.1"},
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: None,
        validate_limit_sell_prices=lambda symbol, prices: None,
    )

    assert place_market_order(
        "SOLUSDT", "SELL", 0.1, dependencies=dependencies, ref_price=100.0
    ) is None
    assert calls == []

    live["value"] = True
    payload = place_market_order(
        "SOLUSDT", "SELL", 0.1, dependencies=dependencies, ref_price=100.0
    )
    assert payload["orderId"] == 99
    assert calls[0][0:2] == ("POST", "/api/v3/order")
    assert calls[0][2]["type"] == "MARKET"
    assert calls[0][2]["quantity"] == "0.100"
    assert journal.get(payload["clientOrderId"]).state == "FILLED"


def test_executor_market_order_halts_on_unconfirmed_response(tmp_path):
    halted = []
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    dependencies = OrderDependencies(
        live=lambda: True,
        logger=lambda message: None,
        pull_filters=lambda symbol: None,
        round_price=lambda symbol, value: value,
        round_qty=lambda symbol, value: round(value, 3),
        min_qty=lambda symbol, hint: 0.001,
        min_notional=lambda symbol, price: 5.0,
        format_price=lambda symbol, value: f"{value:.2f}",
        format_qty=lambda symbol, value: f"{value:.3f}",
        journal=lambda: journal,
        signed_request=lambda method, path, params: {},
        get_order_by_client_id=lambda symbol, client_id: None,
        get_order_list_by_client_id=lambda client_id: None,
        verify_oco_legs=lambda symbol, payload: [],
        cancel_oco=lambda symbol, order_list_id: None,
        halt=lambda reason, **metadata: halted.append((reason, metadata)),
        validate_limit_sell_prices=lambda symbol, prices: None,
    )

    with pytest.raises(RuntimeError, match="no orderId"):
        place_market_order(
            "SOLUSDT", "SELL", 0.1, dependencies=dependencies, ref_price=100.0
        )
    assert halted
    assert journal.nonterminal_orders()[0].state == "UNKNOWN"


def test_executor_planning_is_deterministic_and_exchange_free():
    rounded = lambda value: round(value, 2)
    assert buy_candidates(
        [90.004, 95.0, 100.0, 105.0],
        now_price=100.0,
        occupied_prices={90.0},
        round_price=rounded,
        limit=2,
    ) == [95.0]

    buy = plan_buy_order(
        95.0,
        free_quote=20.0,
        cap_per_order=10.0,
        remaining_slots=2,
        use_all_remaining=False,
        min_order_notional=5.0,
        min_quantity=0.01,
        min_notional=5.0,
        round_price=rounded,
        round_quantity=lambda value: round(value, 3),
    )
    assert buy is not None
    assert buy.price == 95.0
    assert buy.notional <= 10.0

    levels = guarded_sell_levels(
        [90.0, 101.0, 103.0, 105.0],
        now_price=100.0,
        occupied_prices=set(),
        round_price=rounded,
        limit=2,
        average_entry=102.0,
        panic_active=False,
        panic_floor_pct=None,
        profit_floor_pct=0.01,
    )
    assert levels == [105.0]

    sell = plan_sell_order(
        levels[0],
        quantity_left=1.0,
        share=0.5,
        is_last=False,
        min_quantity=0.01,
        min_notional=5.0,
        round_quantity=lambda value: round(value, 3),
    )
    assert sell is not None
    assert sell.quantity == 0.5


def test_executor_runtime_owns_worker_lifecycle_timing():
    sleeps = []
    ticks = list(
        trading_seconds(
            3,
            running=lambda: True,
            sleep=lambda seconds: sleeps.append(seconds),
        )
    )
    assert ticks == [2, 1, 0]
    assert sleeps == [1, 1, 1]
    assert status_due(10, 5)
    assert not status_due(9, 5)


def test_decimal_holdings_planner_never_oversells_or_duplicates_ticks():
    tick = Decimal("0.00000001")
    step = Decimal("0.000001")
    round_price = lambda value: (value // tick) * tick
    round_quantity = lambda value: (value // step) * step
    occupied = existing_prices_decimal(
        [{
            "side": "SELL",
            "type": "LIMIT",
            "price": "75.123456789",
        }],
        side="SELL",
        now_price=Decimal("75"),
        round_price=round_price,
    )
    assert occupied == {Decimal("75.12345678")}

    levels = guarded_sell_levels_decimal(
        [
            Decimal("75.123456789"),
            Decimal("76.000000009"),
            Decimal("77.000000009"),
        ],
        now_price=Decimal("75"),
        occupied_prices=occupied,
        round_price=round_price,
        limit=2,
        average_entry=Decimal("75.5"),
        panic_active=False,
        panic_floor_pct=None,
        profit_floor_pct=Decimal("0.005"),
    )
    assert levels == [Decimal("76.00000000"), Decimal("77.00000000")]

    quantity_left = Decimal("0.123456")
    planned = plan_sell_order_decimal(
        levels[-1],
        quantity_left=quantity_left,
        share=Decimal("0.061728"),
        is_last=True,
        min_quantity=Decimal("0.000001"),
        min_notional=Decimal("5"),
        round_quantity=round_quantity,
    )
    assert planned is not None
    assert planned.quantity == quantity_left
    assert planned.notional == Decimal("9.50611200000000")


def test_decimal_buy_planner_keeps_rounded_notional_under_cap():
    tick = Decimal("0.01")
    step = Decimal("0.001")
    round_price = lambda value: (value // tick) * tick
    round_quantity = lambda value: (value // step) * step
    levels = buy_candidates_decimal(
        [Decimal("76.519"), Decimal("77")],
        now_price=Decimal("76.80"),
        occupied_prices=set(),
        round_price=round_price,
        limit=1,
    )
    assert levels == [Decimal("76.519")]
    planned = plan_buy_order_decimal(
        levels[0],
        free_quote=Decimal("31.09070973"),
        cap_per_order=Decimal("9.62"),
        remaining_slots=1,
        use_all_remaining=False,
        min_order_notional=Decimal("5"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("5"),
        round_price=round_price,
        round_quantity=round_quantity,
    )
    assert planned is not None
    assert planned.price == Decimal("76.51")
    assert planned.quantity == Decimal("0.125")
    assert planned.notional == Decimal("9.56375")
    assert planned.notional <= Decimal("9.62")
