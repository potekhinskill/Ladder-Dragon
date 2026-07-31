from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.verification.live import testnet_smoke as smoke

from ladder_dragon.verification.live.testnet_smoke import (
    build_market_buy,
    build_non_filling_limit_buy,
    build_oco_sell,
    execute_buy_oco_lifecycle,
    run_circuit_drill,
    SpotTestnetClient,
    BinanceTestnetResponseError,
    symbol_rules,
    validate_testnet_base,
)
from ladder_dragon.execution.user_stream import parse_order_signal
from ladder_dragon.verification.live.user_stream_drill import (
    execute_user_stream_drill,
)


def test_smoke_client_refuses_mainnet_and_lookalike_hosts():
    with pytest.raises(ValueError):
        validate_testnet_base("https://api.binance.com")
    with pytest.raises(ValueError):
        validate_testnet_base("https://testnet.binance.vision.attacker.example")
    assert validate_testnet_base("https://testnet.binance.vision/") == (
        "https://testnet.binance.vision"
    )
    with pytest.raises(RuntimeError, match="BINANCE_TESTNET_API_KEY/SECRET"):
        SpotTestnetClient("https://testnet.binance.vision").signed(
            "GET", "/api/v3/account"
        )


def test_signed_testnet_error_never_retains_signed_url():
    class Response:
        status_code = 400
        headers = {"Content-Length": "47"}

        def iter_content(self, chunk_size):
            assert chunk_size == 8192
            yield b'{"code":-1013,"msg":"Filter failure: PRICE_FILTER"}'

        def close(self):
            return None

    class Session:
        headers = {}

        def request(self, method, url, **kwargs):
            assert kwargs["stream"] is True
            assert "signature" in kwargs["params"]
            return Response()

    client = SpotTestnetClient(
        "https://testnet.binance.vision",
        api_key="test-key",
        api_secret="test-secret",
    )
    client.session = Session()

    with pytest.raises(BinanceTestnetResponseError) as captured:
        client.signed("POST", "/api/v3/order", {"symbol": "SOLUSDT"})

    diagnostic = str(captured.value)
    assert diagnostic == (
        "Binance Testnet HTTP 400 code=-1013 endpoint=/api/v3/order"
    )
    assert "signature=" not in diagnostic
    assert "test-secret" not in diagnostic
    assert "test-key" not in diagnostic


def test_signed_testnet_network_error_discards_request_url():
    class Session:
        headers = {}

        def request(self, method, url, **kwargs):
            raise requests.Timeout(
                f"timeout for {url}?signature=temporary-secret"
            )

    client = SpotTestnetClient(
        "https://testnet.binance.vision",
        api_key="test-key",
        api_secret="test-secret",
    )
    client.session = Session()

    with pytest.raises(RuntimeError) as captured:
        client.signed("POST", "/api/v3/order", {"symbol": "SOLUSDT"})

    diagnostic = str(captured.value)
    assert diagnostic == (
        "Binance Testnet network failure: Timeout endpoint=/api/v3/order"
    )
    assert "signature=" not in diagnostic
    assert "temporary-secret" not in diagnostic


def test_testnet_response_rejects_declared_oversize():
    class Response:
        status_code = 200
        headers = {"Content-Length": "65537"}
        closed = False

        def iter_content(self, chunk_size):
            raise AssertionError("oversize response must fail before reading")

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        headers = {}

        def request(self, method, url, **kwargs):
            return response

    client = SpotTestnetClient("https://testnet.binance.vision")
    client.session = Session()

    with pytest.raises(ValueError, match="exceeds the byte limit"):
        client.public_get("/api/v3/time")

    assert response.closed is True


def test_limit_smoke_order_is_below_market_and_respects_filters():
    params = build_non_filling_limit_buy(
        symbol="SOLUSDT",
        market_price="100.00",
        rules={
            "tick": Decimal("0.01"),
            "step": Decimal("0.001"),
            "min_qty": Decimal("0.001"),
            "min_notional": Decimal("5"),
        },
        notional_usdt="10",
    )
    assert Decimal(params["price"]) == Decimal("50.00")
    assert Decimal(params["quantity"]) * Decimal(params["price"]) >= Decimal("10")
    assert params["newClientOrderId"].startswith("LDBSMO-")


def test_user_stream_drill_proves_reconnect_and_event_rest(tmp_path):
    class DrillClient:
        api_key = "key"
        api_secret = "secret"
        base_url = "https://testnet.binance.vision"

        def signed(self, method, path, params=None):
            if method == "POST":
                return {"orderId": 123, "clientOrderId": "drill-order"}
            if method == "GET":
                return {"symbol": "SOLUSDT", "orderId": 123}
            if method == "DELETE":
                return {"status": "CANCELED"}
            raise AssertionError((method, path, params))

    class DrillObserver:
        def __init__(self, **kwargs):
            self.mailbox = kwargs["mailbox"]
            self.payload = {
                "state": "stopped",
                "reconnects": 0,
                "event_woken_rest_reconciliations": 0,
            }

        def start(self):
            self.payload["state"] = "connected"
            signal = parse_order_signal({"event": {
                "e": "executionReport",
                "E": 1,
                "T": 1,
                "s": "SOLUSDT",
                "i": 123,
                "c": "drill-order",
                "x": "NEW",
                "X": "NEW",
                "t": -1,
                "S": "BUY",
                "p": "50",
                "q": "0.2",
            }})
            assert signal is not None
            self.mailbox.put(signal)

        def state(self):
            return dict(self.payload)

        def request_reconnect_drill(self):
            self.payload["reconnects"] += 1

        def record_rest_reconciliation(self, *, event_woken):
            self.payload["event_woken_rest_reconciliations"] += int(
                event_woken
            )

        def stop(self):
            self.payload["state"] = "stopped"

    result = execute_user_stream_drill(
        client=DrillClient(),
        symbol="SOLUSDT",
        order_params={
            "symbol": "SOLUSDT",
            "newClientOrderId": "drill-order",
        },
        state_path=tmp_path / "stream.json",
        clock_offset_ms=0,
        observer_factory=DrillObserver,
    )

    assert result == {
        "controlled_reconnects": 1,
        "order_events": 1,
        "event_woken_rest_reconciliations": 1,
        "rest_remains_authoritative": True,
        "order_cleanup": "canceled",
    }


def test_user_stream_drill_refuses_mainnet_before_start(tmp_path):
    client = SimpleNamespace(
        api_key="key",
        api_secret="secret",
        base_url="https://api.binance.com",
    )

    with pytest.raises(ValueError, match="requires Binance Spot Testnet"):
        execute_user_stream_drill(
            client=client,
            symbol="SOLUSDT",
            order_params={
                "symbol": "SOLUSDT",
                "newClientOrderId": "drill-order",
            },
            state_path=tmp_path / "stream.json",
            clock_offset_ms=0,
        )


def exchange_info():
    return json.loads(
        Path("tests/fixtures/binance/exchange_info_solusdt.json").read_text(
            encoding="utf-8"
        )
    )


def account(sol_free="0", sol_locked="0", usdt_free="1000"):
    return {
        "canTrade": True,
        "balances": [
            {"asset": "SOL", "free": sol_free, "locked": sol_locked},
            {"asset": "USDT", "free": usdt_free, "locked": "0"},
        ],
    }


def test_market_buy_and_oco_builders_use_current_order_list_schema():
    buy = build_market_buy("SOLUSDT", "10")
    assert buy["type"] == "MARKET"
    assert buy["quoteOrderQty"] == "10.00000000"

    oco = build_oco_sell(
        symbol="SOLUSDT",
        quantity="0.100",
        market_price="100",
        rules=symbol_rules(exchange_info()),
        parent_client_order_id=buy["newClientOrderId"],
        take_profit_pct="0.02",
        stop_loss_pct="0.02",
        stop_limit_offset_pct="0.002",
    )
    assert oco["aboveType"] == "LIMIT_MAKER"
    assert oco["abovePrice"] == "102.00"
    assert oco["belowType"] == "STOP_LOSS_LIMIT"
    assert oco["belowStopPrice"] == "98.00"
    assert oco["belowPrice"] == "97.80"
    assert "stopLimitPrice" not in oco


class FakeTestnetClient:
    def __init__(self):
        self.bought = False
        self.cleaned = False
        self.oco_canceled = False
        self.calls = []
        self.buy = None
        self.cleanup_order = None

    def public_get(self, path, params=None):
        assert path == "/api/v3/ticker/price"
        return {"symbol": "SOLUSDT", "price": "100.00"}

    def signed(self, method, path, params=None):
        params = dict(params or {})
        self.calls.append((method, path, params))
        if method == "POST" and path == "/api/v3/order" and params["side"] == "BUY":
            self.bought = True
            self.buy = {
                "symbol": "SOLUSDT",
                "orderId": 101,
                "clientOrderId": params["newClientOrderId"],
                "status": "FILLED",
                "executedQty": "0.100",
                "cummulativeQuoteQty": "10.0",
                "fills": [],
            }
            return dict(self.buy)
        if method == "GET" and path == "/api/v3/order":
            if params.get("orderId") == 203:
                return {
                    "symbol": "SOLUSDT",
                    "orderId": 203,
                    "side": "SELL",
                    "type": "LIMIT_MAKER",
                    "status": "NEW",
                }
            if params.get("orderId") == 204:
                return {
                    "symbol": "SOLUSDT",
                    "orderId": 204,
                    "side": "SELL",
                    "type": "STOP_LOSS_LIMIT",
                    "status": "NEW",
                }
            if self.cleanup_order and params.get("origClientOrderId") == self.cleanup_order[
                "clientOrderId"
            ]:
                return dict(self.cleanup_order)
            return dict(self.buy)
        if method == "GET" and path == "/api/v3/account":
            return account(sol_free="0" if self.cleaned else "0.100", usdt_free="990")
        if method == "POST" and path == "/api/v3/orderList/oco":
            return {
                "orderListId": 202,
                "listClientOrderId": params["listClientOrderId"],
                "listStatusType": "EXEC_STARTED",
            }
        if method == "GET" and path == "/api/v3/orderList":
            return {
                "orderListId": 202,
                "listClientOrderId": params.get("origClientOrderId", "oco"),
                "listStatusType": "ALL_DONE" if self.oco_canceled else "EXEC_STARTED",
                "orders": [
                    {"symbol": "SOLUSDT", "orderId": 203, "clientOrderId": "tp"},
                    {"symbol": "SOLUSDT", "orderId": 204, "clientOrderId": "sl"},
                ],
            }
        if method == "DELETE" and path == "/api/v3/orderList":
            self.oco_canceled = True
            return {"orderListId": 202, "listStatusType": "ALL_DONE"}
        if method == "POST" and path == "/api/v3/order" and params["side"] == "SELL":
            self.cleaned = True
            self.cleanup_order = {
                "symbol": "SOLUSDT",
                "orderId": 303,
                "clientOrderId": params["newClientOrderId"],
                "status": "FILLED",
                "executedQty": params["quantity"],
                "cummulativeQuoteQty": "9.9",
            }
            return dict(self.cleanup_order)
        raise AssertionError(f"unexpected request: {method} {path} {params}")


@pytest.mark.parametrize("journal_reload_drill", [False, True])
def test_buy_oco_lifecycle_verifies_and_cleans_position(
    tmp_path, journal_reload_drill
):
    client = FakeTestnetClient()
    result = execute_buy_oco_lifecycle(
        client=client,
        symbol="SOLUSDT",
        exchange_info=exchange_info(),
        account_before=account(),
        notional_usdt="10",
        max_notional_usdt="25",
        reserve_usdt="100",
        take_profit_pct="0.02",
        stop_loss_pct="0.02",
        stop_limit_offset_pct="0.002",
        journal_path=tmp_path / "testnet.sqlite3",
        journal_reload_drill=journal_reload_drill,
    )
    assert result["market_buy"] == "filled"
    assert result["oco"] == "verified"
    assert result["verified_oco_leg_types"] == ["LIMIT_MAKER", "STOP_LOSS_LIMIT"]
    assert result["journal_reload_reconciled"] is journal_reload_drill
    assert client.cleaned
    assert OrderJournal(tmp_path / "testnet.sqlite3").unresolved_buys("SOLUSDT") == []
    assert any(
        method == "POST" and path == "/api/v3/orderList/oco"
        for method, path, _ in client.calls
    )
    assert any(
        method == "DELETE" and path == "/api/v3/orderList"
        for method, path, _ in client.calls
    )


class UncertainOcoClient(FakeTestnetClient):
    def __init__(self, *, recoverable=True):
        super().__init__()
        self.recoverable = recoverable

    def signed(self, method, path, params=None):
        if method == "POST" and path == "/api/v3/orderList/oco":
            self.calls.append((method, path, dict(params or {})))
            raise requests.ConnectionError("OCO ACK lost")
        if method == "GET" and path == "/api/v3/orderList" and not self.recoverable:
            self.calls.append((method, path, dict(params or {})))
            raise requests.ConnectionError("OCO reconciliation unavailable")
        return super().signed(method, path, params)


def lifecycle_args(tmp_path, client, **overrides):
    values = dict(
        client=client,
        symbol="SOLUSDT",
        exchange_info=exchange_info(),
        account_before=account(),
        notional_usdt="10",
        max_notional_usdt="25",
        reserve_usdt="100",
        take_profit_pct="0.02",
        stop_loss_pct="0.02",
        stop_limit_offset_pct="0.002",
        journal_path=tmp_path / "testnet.sqlite3",
    )
    values.update(overrides)
    return values


def test_lost_oco_ack_is_reconciled_without_duplicate(tmp_path):
    client = UncertainOcoClient()
    result = execute_buy_oco_lifecycle(**lifecycle_args(tmp_path, client))
    assert result["oco"] == "verified"
    assert sum(
        method == "POST" and path == "/api/v3/orderList/oco"
        for method, path, _ in client.calls
    ) == 1
    assert client.cleaned


def test_unrecoverable_oco_failure_still_flattens_test_position(tmp_path):
    client = UncertainOcoClient(recoverable=False)
    with pytest.raises(RuntimeError, match="uncertain Testnet OCO"):
        execute_buy_oco_lifecycle(**lifecycle_args(tmp_path, client))
    assert client.cleaned


def test_buy_oco_refuses_to_violate_testnet_reserve(tmp_path):
    client = FakeTestnetClient()
    with pytest.raises(RuntimeError, match="reserve would be violated"):
        execute_buy_oco_lifecycle(
            **lifecycle_args(
                tmp_path,
                client,
                account_before=account(usdt_free="105"),
            )
        )
    assert not client.bought


def test_circuit_drill_proves_restart_persistence_and_manual_reset(tmp_path):
    result = run_circuit_drill(tmp_path / "drill")
    assert result["circuit_drill"] == "passed"
    assert result["halt_survived_restart"] is True
    assert result["manual_reset_verified"] is True
    assert not (tmp_path / "drill" / "circuit_halt.json").exists()


def test_circuit_drill_run_is_fully_offline(tmp_path, monkeypatch):
    def refuse_client(*args, **kwargs):
        raise AssertionError("circuit drill must not construct an exchange client")

    monkeypatch.setattr(smoke, "SpotTestnetClient", refuse_client)
    result = smoke.run(
        SimpleNamespace(
            mode="circuit-drill",
            symbol="SOLUSDT",
            drill_dir=tmp_path / "offline-drill",
        )
    )

    assert result["venue"] == "isolated-local"
    assert result["circuit_drill"] == "passed"


def test_gap_drill_is_fully_offline(monkeypatch, tmp_path):
    def refuse_client(*args, **kwargs):
        raise AssertionError("gap drill must not construct an exchange client")

    monkeypatch.setattr(smoke, "SpotTestnetClient", refuse_client)
    result = smoke.run(
        SimpleNamespace(
            mode="gap-drill", symbol="SOLUSDT", drill_dir=tmp_path / "gap"
        )
    )
    assert result == {
        "venue": "isolated-local",
        "symbol": "SOLUSDT",
        "mode": "gap-drill",
        "gap_drill": "passed",
        "oco_cancel_verified": True,
        "market_flatten_verified": True,
        "partial_stop_residual_verified": True,
        "lost_cancel_ack_halted": True,
        "halt_survived_restart": True,
        "network_used": False,
    }


class LostCleanupAckClient(FakeTestnetClient):
    def signed(self, method, path, params=None):
        if method == "DELETE" and path == "/api/v3/orderList":
            super().signed(method, path, params)
            raise requests.ConnectionError("cancel ACK lost")
        if (
            method == "POST"
            and path == "/api/v3/order"
            and (params or {}).get("side") == "SELL"
        ):
            super().signed(method, path, params)
            raise requests.ConnectionError("cleanup SELL ACK lost")
        return super().signed(method, path, params)


def test_cleanup_lost_acks_are_reconciled(tmp_path):
    client = LostCleanupAckClient()
    result = execute_buy_oco_lifecycle(**lifecycle_args(tmp_path, client))
    assert result["oco"] == "verified"
    assert client.oco_canceled
    assert client.cleaned
