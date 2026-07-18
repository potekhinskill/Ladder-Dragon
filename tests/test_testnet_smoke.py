from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from ladder_dragon.execution.order_recovery import OrderJournal
import binance_testnet_smoke as smoke

from binance_testnet_smoke import (
    build_market_buy,
    build_non_filling_limit_buy,
    build_oco_sell,
    execute_buy_oco_lifecycle,
    run_circuit_drill,
    SpotTestnetClient,
    symbol_rules,
    validate_testnet_base,
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


@pytest.mark.parametrize("restart_drill", [False, True])
def test_buy_oco_lifecycle_verifies_and_cleans_position(tmp_path, restart_drill):
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
        restart_drill=restart_drill,
    )
    assert result["market_buy"] == "filled"
    assert result["oco"] == "verified"
    assert result["verified_oco_leg_types"] == ["LIMIT_MAKER", "STOP_LOSS_LIMIT"]
    assert result["restart_reconciled"] is restart_drill
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
