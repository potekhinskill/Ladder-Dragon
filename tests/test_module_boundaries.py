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
from ladder_dragon.execution.executor_market import (
    get_balances,
    get_price,
    get_price_decimal,
    get_symbol_assets,
)
from ladder_dragon.execution.orders.runtime import (
    OrderDependencies,
    place_limit_order,
    place_market_order,
    place_oco_sell,
    place_otoco_buy,
)
from ladder_dragon.execution.executor_planning import (
    buy_candidates_decimal,
    existing_prices_decimal,
    guarded_sell_levels_decimal,
    plan_buy_order_decimal,
    plan_sell_order_decimal,
)
from ladder_dragon.execution.executor_recovery import get_order_by_client_id, verify_oco_legs
from ladder_dragon.execution.executor_runtime import (
    status_due,
    trading_seconds,
    trading_wakeups,
)
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
from ladder_dragon.supervision.config import build_supervisor_parser, validate_supervisor_args


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


@pytest.mark.parametrize(
    ("argument", "approval"),
    [
        ("--fast-market-mode", "BOT_FAST_MARKET_APPROVED"),
        ("--otoco-mode", "BOT_OTOCO_APPROVED"),
        ("--ws-trading-mode", "BOT_WS_TRADING_APPROVED"),
    ],
)
def test_live_low_latency_apply_requires_independent_approval(
    monkeypatch,
    argument,
    approval,
):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    monkeypatch.delenv(approval, raising=False)
    parser = build_executor_parser()
    args = parser.parse_args([
        "--symbol",
        "SOLUSDT",
        "--ladder-prices",
        "90,110",
        "--live",
        argument,
        "APPLY",
    ])

    with pytest.raises(SystemExit) as exc:
        validate_executor_args(parser, args)

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
    assert args.dir_up_dev_mult < 1
    assert args.dir_down_dev_mult > 1

    invalid = argparse.Namespace(**{**vars(args), "dir_up_dev_mult": 0})
    with pytest.raises(SystemExit) as exc:
        validate_supervisor_args(parser, invalid)
    assert exc.value.code == 2


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


def test_panic_ignores_tiny_atr_noise_but_keeps_real_downside_guard():
    assert not panic_triggered(
        99.92,
        100.0,
        0.02,
        100.0,
        0.02,
        2.0,
    )
    assert panic_triggered(
        99.40,
        100.0,
        0.02,
        100.0,
        0.02,
        2.0,
    )


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
    calls = []

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
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
    assert len(calls) == 1
    assert not any("[RETRY]" in message for message in messages)


def test_signed_read_retries_only_three_times(monkeypatch):
    calls = []
    messages = []

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
            raise requests.Timeout("read unavailable")

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

    with pytest.raises(BinanceNetworkError):
        transport.signed_request("GET", "/api/v3/account")

    assert len(calls) == 3
    assert sum("[RETRY]" in message for message in messages) == 2


def test_mutating_http_5xx_is_one_unknown_outcome_without_retry(monkeypatch):
    calls = []
    messages = []

    class Response:
        status_code = 503
        headers = {}
        text = ""

        @staticmethod
        def json():
            return {"code": -1000, "msg": "unknown execution status"}

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
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

    with pytest.raises(BinanceNetworkError) as caught:
        transport.signed_request(
            "POST", "/api/v3/order", {"newClientOrderId": "SAFE-ID"}
        )

    assert caught.value.cause_type == "HTTP503"
    assert len(calls) == 1
    assert not any("[RETRY]" in message for message in messages)


def test_http_418_arms_local_retry_after_cooldown_without_network_retry():
    calls = []
    messages = []

    class Response:
        status_code = 418
        headers = {"Retry-After": "600"}
        text = ""

        @staticmethod
        def json():
            return {"code": -1003, "msg": "IP banned"}

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
            return Response()

    transport = BinanceTransport(
        Session(),
        base_url=lambda: "https://api.binance.com",
        api_key=lambda: "key",
        api_secret=lambda: "secret",
        live=lambda: True,
        recv_window=lambda: 5000,
        logger=messages.append,
    )

    with pytest.raises(BinanceResponseError) as first:
        transport.signed_request("GET", "/api/v3/account")
    with pytest.raises(BinanceResponseError) as second:
        transport.signed_request("GET", "/api/v3/account")

    assert first.value.status == 418
    assert first.value.retry_after_seconds == 600
    assert second.value is first.value
    assert len(calls) == 1
    assert sum("[IP-BAN]" in message for message in messages) == 1


def test_http_429_uses_local_cooldown_instead_of_blocking_sleep(monkeypatch):
    calls = []
    messages = []
    sleeps = []

    class Response:
        status_code = 429
        headers = {"Retry-After": "3"}
        text = ""

        @staticmethod
        def json():
            return {"code": -1003, "msg": "too many requests"}

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
            return Response()

    monkeypatch.setattr(
        "ladder_dragon.execution.binance_transport.time.sleep", sleeps.append
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

    with pytest.raises(BinanceResponseError) as first:
        transport.public_get("/api/v3/time")
    with pytest.raises(BinanceResponseError) as second:
        transport.public_get("/api/v3/time")

    assert first.value.status == 429
    assert first.value.retry_after_seconds == 3
    assert second.value is first.value
    assert len(calls) == 1
    assert sleeps == []
    assert sum("[RATE-LIMIT]" in message for message in messages) == 1


def test_clock_rejection_resyncs_before_one_safe_mutation_retry():
    calls = []
    now_ms = 1_700_000_000_000

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.payload = payload
            self.headers = {}
            self.text = ""

        def json(self):
            return self.payload

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url))
            if url.endswith("/api/v3/time"):
                return Response(200, {"serverTime": now_ms + 5000})
            order_calls = [item for item in calls if "/api/v3/order?" in item[1]]
            if len(order_calls) == 1:
                return Response(400, {"code": -1021, "msg": "timestamp outside window"})
            return Response(200, {"orderId": 123, "status": "NEW"})

    transport = BinanceTransport(
        Session(),
        base_url=lambda: "https://api.binance.com",
        api_key=lambda: "key",
        api_secret=lambda: "secret",
        live=lambda: True,
        recv_window=lambda: 5000,
        logger=lambda message: None,
        timestamp_ms=lambda: now_ms,
    )

    result = transport.signed_request(
        "POST", "/api/v3/order", {"newClientOrderId": "CLOCK-ID"}
    )

    order_urls = [url for method, url in calls if "/api/v3/order?" in url]
    assert result["orderId"] == 123
    assert len(order_urls) == 2
    assert "timestamp=1700000000000" in order_urls[0]
    assert "timestamp=1700000005000" in order_urls[1]
    assert [method for method, url in calls if url.endswith("/api/v3/time")] == ["GET"]


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

    assert get_price_decimal(
        "SOLUSDT", public_get=public_get, logger=lambda message: None
    ) == Decimal("100")
    assert get_price(
        "SOLUSDT",
        public_get=lambda *_args: {"price": "100.125"},
        logger=lambda message: None,
    ) == 100.125
    assert calls == ["/api/v3/ticker/price", "/api/v3/ticker/bookTicker"]

    with pytest.raises(ValueError, match="finite and positive"):
        get_price_decimal(
            "SOLUSDT",
            public_get=lambda *_args: {"price": "NaN"},
            logger=lambda message: None,
        )

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

    def unavailable(_symbol):
        raise requests.ConnectionError("exchange info unavailable")

    assert get_symbol_assets(
        "ETHBTC", exchange_info=unavailable, cache={}
    ) == ("ETH", "BTC")
    assert get_symbol_assets(
        "SOLFDUSD", exchange_info=unavailable, cache={}
    ) == ("SOL", "FDUSD")
    with pytest.raises(ValueError, match="cannot determine assets"):
        get_symbol_assets(
            "ABCXYZ", exchange_info=unavailable, cache={}
        )

    balances = get_balances(
        signed_request=lambda *args: {
            "balances": [{"asset": "USDT", "free": "10.5", "locked": "1.5"}]
        }
    )
    assert balances["USDT"] == {
        "free": Decimal("10.5"),
        "locked": Decimal("1.5"),
    }

    with pytest.raises(ValueError, match="invalid account balance"):
        get_balances(
            signed_request=lambda *args: {
                "balances": [
                    {"asset": "USDT", "free": "NaN", "locked": "0"}
                ]
            }
        )
