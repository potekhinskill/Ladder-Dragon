from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from bin import binance_mainnet_canary as canary
from bin.binance_testnet_smoke import symbol_rules, validate_sell_percent_prices
from ladder_dragon.execution.order_recovery import OrderJournal


def exchange_info():
    payload = json.loads(
        Path("tests/fixtures/binance/exchange_info_solusdt.json").read_text(
            encoding="utf-8"
        )
    )
    payload["symbols"][0]["status"] = "TRADING"
    payload["symbols"][0]["isSpotTradingAllowed"] = True
    payload["symbols"][0]["filters"].append(
        {
            "filterType": "PERCENT_PRICE_BY_SIDE",
            "bidMultiplierUp": "5",
            "bidMultiplierDown": "0.2",
            "askMultiplierUp": "5",
            "askMultiplierDown": "0.2",
            "avgPriceMins": 5,
        }
    )
    return payload


class FakeMainnetClient:
    def __init__(self) -> None:
        self.bought = False
        self.cleaned = False
        self.oco_canceled = False
        self.buy = None
        self.cleanup_order = None
        self.calls = []

    def public_get(self, path, params=None):
        if path == "/api/v3/time":
            import time

            return {"serverTime": int(time.time() * 1000)}
        if path == "/api/v3/exchangeInfo":
            return exchange_info()
        if path == "/api/v3/ticker/price":
            return {"symbol": "SOLUSDT", "price": "100.00"}
        if path == "/api/v3/avgPrice":
            return {"mins": 5, "price": "100.00"}
        raise AssertionError(f"unexpected public request: {path} {params}")

    def _account(self):
        sol = "1.000" if self.cleaned or not self.bought else "1.060"
        usdt = "399.90" if self.cleaned else ("394.00" if self.bought else "400.00")
        return {
            "canTrade": True,
            "balances": [
                {"asset": "SOL", "free": sol, "locked": "0"},
                {"asset": "USDT", "free": usdt, "locked": "0"},
            ],
        }

    def signed(self, method, path, params=None):
        params = dict(params or {})
        self.calls.append((method, path, params))
        if method == "GET" and path == "/api/v3/account":
            return self._account()
        if method == "GET" and path == "/api/v3/account/commission":
            return {
                "symbol": "SOLUSDT",
                "standardCommission": {
                    "maker": "0.001",
                    "taker": "0.001",
                    "buyer": "0",
                    "seller": "0",
                },
                "taxCommission": {
                    "maker": "0",
                    "taker": "0",
                    "buyer": "0",
                    "seller": "0",
                },
                "specialCommission": {
                    "maker": "0",
                    "taker": "0",
                    "buyer": "0",
                    "seller": "0",
                },
            }
        if method == "GET" and path == "/api/v3/openOrders":
            return []
        if method == "POST" and path == "/api/v3/order" and params["side"] == "BUY":
            self.bought = True
            self.buy = {
                "symbol": "SOLUSDT",
                "orderId": 101,
                "clientOrderId": params["newClientOrderId"],
                "status": "FILLED",
                "executedQty": "0.060",
                "cummulativeQuoteQty": "6.00",
                "fills": [
                    {"commissionAsset": "BNB", "commission": "0.00001"}
                ],
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
                "cummulativeQuoteQty": "5.90",
                "fills": [
                    {"commissionAsset": "BNB", "commission": "0.00001"}
                ],
            }
            return dict(self.cleanup_order)
        raise AssertionError(f"unexpected signed request: {method} {path} {params}")


def args(tmp_path, **overrides):
    values = dict(
        symbol="SOLUSDT",
        notional_usdt=Decimal("6"),
        take_profit_pct=Decimal("0.02"),
        stop_loss_pct=Decimal("0.02"),
        stop_limit_offset_pct=Decimal("0.002"),
        journal=str(tmp_path / "mainnet-canary.sqlite3"),
        production_journal=str(tmp_path / "production.sqlite3"),
        report=str(tmp_path / "mainnet-canary.ndjson"),
        lock_file=str(tmp_path / "mainnet-canary.lock"),
        max_commission_usdt=Decimal("0.02"),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def confirmed_env():
    return {
        "BOT_LIVE_CONFIRMED": "YES",
        "BOT_MAINNET_CANARY_CONFIRMED": "YES",
        "BOT_MAINNET_CANARY_CLEANUP_CONFIRMED": "YES",
        "RISK_RESERVE_USDT": "300",
    }


def test_mainnet_origin_is_strict():
    assert canary.validate_mainnet_base("https://api.binance.com/") == (
        "https://api.binance.com"
    )
    for unsafe in (
        "http://api.binance.com",
        "https://testnet.binance.vision",
        "https://api.binance.com.attacker.example",
        "https://api.binance.com/api",
        "https://user:pass@api.binance.com",
    ):
        with pytest.raises(ValueError):
            canary.validate_mainnet_base(unsafe)


def test_relative_runtime_paths_are_project_rooted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert canary.resolve_project_path("db/canary.sqlite3") == (
        canary.PROJECT_ROOT / "db/canary.sqlite3"
    )
    absolute = tmp_path / "absolute.sqlite3"
    assert canary.resolve_project_path(absolute) == absolute


def test_default_lock_is_project_private_and_not_systemd_runtime():
    parsed = canary.build_parser().parse_args([])
    assert parsed.lock_file == ".runtime/mainnet-canary.lock"
    assert canary.resolve_project_path(parsed.lock_file) == (
        canary.PROJECT_ROOT / ".runtime/mainnet-canary.lock"
    )


def test_exclusive_lock_creates_private_project_rooted_file(monkeypatch, tmp_path):
    monkeypatch.setattr(canary, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    with canary.exclusive_lock(".runtime/canary.lock"):
        target = tmp_path / ".runtime/canary.lock"
        assert target.exists()
        assert target.stat().st_mode & 0o777 == 0o600


def test_exclusive_lock_converts_permission_failure(monkeypatch, tmp_path):
    def denied(*_args, **_kwargs):
        raise PermissionError("host path intentionally hidden")

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(
        RuntimeError,
        match="cannot create private Mainnet canary lock: PermissionError",
    ):
        with canary.exclusive_lock(tmp_path / "blocked" / "canary.lock"):
            pass


def test_mainnet_canary_requires_every_confirmation(tmp_path):
    env = confirmed_env()
    env.pop("BOT_MAINNET_CANARY_CLEANUP_CONFIRMED")
    with pytest.raises(RuntimeError, match="CLEANUP_CONFIRMED"):
        canary.run_canary(
            args(tmp_path),
            environ=env,
            client=FakeMainnetClient(),
            service_check=lambda: None,
        )


def test_mainnet_canary_refuses_active_service():
    def active_runner(*_args, **_kwargs):
        return SimpleNamespace(stdout="active\n", returncode=0)

    with pytest.raises(RuntimeError, match="mybot.service is active"):
        canary.require_services_stopped(active_runner)


def test_mainnet_canary_refuses_running_watchdog_oneshot():
    def runner(command, **_kwargs):
        unit = command[-1]
        state = "active" if unit == "pi-watchdog-v3.service" else "inactive"
        return SimpleNamespace(stdout=f"{state}\n", returncode=0)

    with pytest.raises(RuntimeError, match="pi-watchdog-v3.service is active"):
        canary.require_services_stopped(runner)


def test_mainnet_canary_hard_caps_notional(tmp_path):
    with pytest.raises(RuntimeError, match=r"\(0, 10\]"):
        canary.run_canary(
            args(tmp_path, notional_usdt=Decimal("10.01")),
            environ=confirmed_env(),
            client=FakeMainnetClient(),
            service_check=lambda: None,
        )


def test_mainnet_canary_refuses_commission_above_budget(tmp_path):
    with pytest.raises(RuntimeError, match="estimated.*exceeds budget"):
        canary.run_canary(
            args(tmp_path, max_commission_usdt=Decimal("0.01")),
            environ=confirmed_env(),
            client=FakeMainnetClient(),
            service_check=lambda: None,
        )


def test_mainnet_canary_is_one_success_per_release(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    OrderJournal(args(tmp_path).production_journal, venue="mainnet")
    canary.run_canary(
        args(tmp_path),
        environ=confirmed_env(),
        client=FakeMainnetClient(),
        service_check=lambda: None,
    )

    with pytest.raises(RuntimeError, match="already passed for release"):
        canary.run_canary(
            args(tmp_path),
            environ=confirmed_env(),
            client=FakeMainnetClient(),
            service_check=lambda: None,
        )


def test_mainnet_canary_refuses_nonterminal_production_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    production = OrderJournal(args(tmp_path).production_journal, venue="mainnet")
    production.prepare(
        client_order_id="LDBLAD-pending",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="75",
    )
    with pytest.raises(RuntimeError, match="nonterminal intents"):
        canary.run_canary(
            args(tmp_path),
            environ=confirmed_env(),
            client=FakeMainnetClient(),
            service_check=lambda: None,
        )


def test_mainnet_canary_completes_exact_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    OrderJournal(args(tmp_path).production_journal, venue="mainnet")
    client = FakeMainnetClient()
    result = canary.run_canary(
        args(tmp_path),
        environ=confirmed_env(),
        client=client,
        service_check=lambda: None,
    )

    assert result["status"] == "passed"
    assert result["canary_id"] == result["buy_client_order_id"]
    assert result["preflight"]["production_journal_pending"] == 0
    assert result["preflight"]["filters"]["min_notional"] == "5.00000000"
    assert result["market_buy"] == "filled"
    assert result["oco"] == "verified"
    assert result["verified_oco_leg_types"] == ["LIMIT_MAKER", "STOP_LOSS_LIMIT"]
    assert result["restart_reconciled"] is True
    assert result["cleanup"] == "OCO canceled and canary position flattened"
    assert result["open_orders_after"] == 0
    assert Decimal(result["quote_balance_delta_usdt"]) == Decimal("-0.10")
    assert Decimal(result["gross_quote_pnl_usdt"]) == Decimal("-0.10")
    assert result["fees_by_asset"] == {"BNB": "0.00002"}
    assert Decimal(result["commission_usdt"]) == Decimal("0.00200000")
    assert result["preflight"]["commission"] == {
        "buy_rate": "0.001",
        "sell_rate": "0.001",
        "estimated_max_commission_usdt": "0.01260000",
        "commission_budget_usdt": "0.02",
    }
    assert Decimal(result["buy_latency_ms"]) >= 0
    assert Decimal(result["oco_latency_ms"]) >= 0
    assert client.cleaned and client.oco_canceled

    journal = OrderJournal(args(tmp_path).journal, venue="mainnet-canary")
    buy = journal.get(result["buy_client_order_id"])
    assert buy is not None and buy.state == "CLOSED"
    report = json.loads(Path(args(tmp_path).report).read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert "api_key" not in json.dumps(report).lower()
    assert Path(args(tmp_path).report).stat().st_mode & 0o777 == 0o600


class UnrecoverableOcoClient(FakeMainnetClient):
    def signed(self, method, path, params=None):
        if method == "POST" and path == "/api/v3/orderList/oco":
            raise requests.ConnectionError("ACK unavailable")
        if method == "GET" and path == "/api/v3/orderList":
            raise requests.ConnectionError("reconciliation unavailable")
        return super().signed(method, path, params)


class NonTerminalCancelClient(FakeMainnetClient):
    def signed(self, method, path, params=None):
        if method == "DELETE" and path == "/api/v3/orderList":
            return {"orderListId": 202, "listStatusType": "EXEC_STARTED"}
        return super().signed(method, path, params)


class UnexpectedHighActualCommissionClient(FakeMainnetClient):
    def signed(self, method, path, params=None):
        payload = super().signed(method, path, params)
        if (
            method == "POST"
            and path == "/api/v3/order"
            and isinstance(payload, dict)
            and payload.get("status") == "FILLED"
        ):
            payload["fills"] = [
                {"commissionAsset": "BNB", "commission": "0.00020"}
            ]
            if params and params.get("side") == "BUY":
                self.buy = payload
            if params and params.get("side") == "SELL":
                self.cleanup_order = payload
        return payload


def test_post_buy_failure_creates_persistent_halt(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    monkeypatch.setenv("BOT_RUN_DIR", str(run_dir))
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    OrderJournal(args(tmp_path).production_journal, venue="mainnet")
    with pytest.raises(RuntimeError, match="failed closed"):
        canary.run_canary(
            args(tmp_path),
            environ=confirmed_env(),
            client=UnrecoverableOcoClient(),
            service_check=lambda: None,
        )
    assert (run_dir / "circuit_halt.json").exists()
    report = json.loads(Path(args(tmp_path).report).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["error_type"] == "RuntimeError"


def test_oco_cancel_must_reach_all_done(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    monkeypatch.setenv("BOT_RUN_DIR", str(run_dir))
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    OrderJournal(args(tmp_path).production_journal, venue="mainnet")
    with pytest.raises(RuntimeError, match="ALL_DONE"):
        canary.run_canary(
            args(tmp_path),
            environ=confirmed_env(),
            client=NonTerminalCancelClient(),
            service_check=lambda: None,
        )
    assert (run_dir / "circuit_halt.json").exists()


def test_actual_commission_over_budget_halts_after_cleanup(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    monkeypatch.setenv("BOT_RUN_DIR", str(run_dir))
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    OrderJournal(args(tmp_path).production_journal, venue="mainnet")

    with pytest.raises(RuntimeError, match="actual.*exceeds budget"):
        canary.run_canary(
            args(tmp_path),
            environ=confirmed_env(),
            client=UnexpectedHighActualCommissionClient(),
            service_check=lambda: None,
        )

    assert (run_dir / "circuit_halt.json").exists()
    report = json.loads(Path(args(tmp_path).report).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert Decimal(report["commission_usdt"]) > Decimal("0.02")


def test_oco_builder_still_respects_mainnet_filters():
    rules = symbol_rules(exchange_info())
    assert rules["min_notional"] == Decimal("5.00000000")
    assert validate_sell_percent_prices(
        exchange_info(),
        reference_price="100",
        prices=["102", "98", "97.8"],
    )
    with pytest.raises(RuntimeError, match="outside Binance"):
        validate_sell_percent_prices(
            exchange_info(),
            reference_price="100",
            prices=["600"],
        )
