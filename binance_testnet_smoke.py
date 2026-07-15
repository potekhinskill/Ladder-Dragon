#!/usr/bin/env python3
"""Fail-closed Binance Spot Testnet smoke checks.

The client refuses every host except testnet.binance.vision.  The default mode
is read-only; mutating modes require a separate explicit confirmation.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from dotenv import load_dotenv

from exchange_math import decimal, format_step, normalized_order_values, round_step
from order_identity import client_order_id
from order_recovery import OrderJournal
from risk_manager import RiskLimits, RiskManager, RiskSnapshot
from time_safety import assess_exchange_clock


DEFAULT_BASE = "https://testnet.binance.vision"
ALLOWED_HOST = "testnet.binance.vision"


def validate_testnet_base(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST or parsed.username or parsed.password:
        raise ValueError(f"refusing non-Testnet Binance URL: {base_url}")
    return f"https://{ALLOWED_HOST}"


class SpotTestnetClient:
    def __init__(self, base_url: str, api_key: str = "", api_secret: str = "") -> None:
        self.base_url = validate_testnet_base(base_url)
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "LadderDragon/TestnetSmoke"})
        if api_key:
            self.session.headers.update({"X-MBX-APIKEY": api_key})

    def public_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(self.base_url + path, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def signed(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("BINANCE_TESTNET_API_KEY/SECRET are required")
        payload = dict(params or {})
        payload["recvWindow"] = 5000
        payload["timestamp"] = int(time.time() * 1000)
        query = urlencode(payload)
        payload["signature"] = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        response = self.session.request(
            method.upper(), self.base_url + path, params=payload, timeout=10
        )
        response.raise_for_status()
        return response.json()


def symbol_rules(exchange_info: dict[str, Any]) -> dict[str, Decimal]:
    symbols = exchange_info.get("symbols") or []
    if len(symbols) != 1:
        raise RuntimeError("exchangeInfo did not return exactly one symbol")
    filters = {item["filterType"]: item for item in symbols[0].get("filters", [])}
    notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
    rules = {
        "tick": decimal((filters.get("PRICE_FILTER") or {}).get("tickSize")),
        "step": decimal((filters.get("LOT_SIZE") or {}).get("stepSize")),
        "min_qty": decimal((filters.get("LOT_SIZE") or {}).get("minQty")),
        "min_notional": decimal(notional_filter.get("minNotional")),
    }
    if any(value <= 0 for value in rules.values()):
        raise RuntimeError(f"invalid exchange filters: {rules}")
    return rules


def build_non_filling_limit_buy(
    *,
    symbol: str,
    market_price: object,
    rules: dict[str, Decimal],
    notional_usdt: object,
) -> dict[str, str]:
    market = decimal(market_price)
    requested_notional = max(decimal(notional_usdt), rules["min_notional"] * Decimal("1.1"))
    raw_price = market * Decimal("0.50")
    qty, price = normalized_order_values(
        requested_notional / raw_price,
        raw_price,
        step=rules["step"],
        tick=rules["tick"],
        min_qty=rules["min_qty"],
        min_notional=rules["min_notional"],
        side="BUY",
    )
    return {
        "symbol": symbol,
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": qty,
        "price": price,
        "newOrderRespType": "RESULT",
        "newClientOrderId": client_order_id(
            symbol, "BUY", "smoke", price, qty, bucket_seconds=1
        ),
    }


def symbol_assets(exchange_info: dict[str, Any]) -> tuple[str, str]:
    symbols = exchange_info.get("symbols") or []
    if len(symbols) != 1:
        raise RuntimeError("exchangeInfo did not return exactly one symbol")
    base = str(symbols[0].get("baseAsset") or "").upper()
    quote = str(symbols[0].get("quoteAsset") or "").upper()
    if not base or not quote:
        raise RuntimeError("exchangeInfo has no baseAsset/quoteAsset")
    return base, quote


def balance_amount(account: dict[str, Any], asset: str, field: str = "free") -> Decimal:
    for row in account.get("balances") or []:
        if str(row.get("asset") or "").upper() == asset.upper():
            return decimal(row.get(field) or "0")
    return Decimal("0")


def build_market_buy(symbol: str, notional_usdt: object) -> dict[str, str]:
    quote_qty = decimal(notional_usdt)
    if quote_qty <= 0:
        raise ValueError("market BUY notional must be > 0")
    quote_s = f"{quote_qty:.8f}"
    return {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": quote_s,
        "newOrderRespType": "FULL",
        "newClientOrderId": client_order_id(
            symbol, "BUY", "testnet_market", "MARKET", quote_s, bucket_seconds=1
        ),
    }


def build_oco_sell(
    *,
    symbol: str,
    quantity: object,
    market_price: object,
    rules: dict[str, Decimal],
    parent_client_order_id: str,
    take_profit_pct: object,
    stop_loss_pct: object,
    stop_limit_offset_pct: object,
) -> dict[str, str]:
    market = decimal(market_price)
    tp_pct = decimal(take_profit_pct)
    sl_pct = decimal(stop_loss_pct)
    offset = decimal(stop_limit_offset_pct)
    if market <= 0 or not Decimal("0") < tp_pct < Decimal("0.25"):
        raise ValueError("invalid market price or take-profit percentage")
    if not Decimal("0") < sl_pct < Decimal("0.25"):
        raise ValueError("stop-loss percentage must be between 0 and 0.25")
    if not Decimal("0") < offset < sl_pct:
        raise ValueError("stop-limit offset must be positive and smaller than stop loss")
    qty = round_step(quantity, rules["step"], "floor")
    tp = round_step(market * (Decimal("1") + tp_pct), rules["tick"], "ceil")
    stop = round_step(market * (Decimal("1") - sl_pct), rules["tick"], "floor")
    stop_limit = round_step(stop * (Decimal("1") - offset), rules["tick"], "floor")
    if not tp > market > stop > stop_limit > 0:
        raise RuntimeError("normalized OCO prices are not ordered around market")
    if qty < rules["min_qty"] or qty * stop_limit < rules["min_notional"]:
        raise RuntimeError("acquired quantity is too small for a protected OCO")
    qty_s = format_step(qty, rules["step"])
    tp_s = format_step(tp, rules["tick"])
    stop_s = format_step(stop, rules["tick"])
    stop_limit_s = format_step(stop_limit, rules["tick"])
    list_client_id = client_order_id(
        symbol,
        "SELL",
        f"testnet_oco:{parent_client_order_id[:10]}",
        tp_s,
        qty_s,
        bucket_seconds=1,
    )
    return {
        "symbol": symbol,
        "side": "SELL",
        "quantity": qty_s,
        "aboveType": "LIMIT_MAKER",
        "abovePrice": tp_s,
        "belowType": "STOP_LOSS_LIMIT",
        "belowStopPrice": stop_s,
        "belowPrice": stop_limit_s,
        "belowTimeInForce": "GTC",
        "newOrderRespType": "RESULT",
        "listClientOrderId": list_client_id,
        "aboveClientOrderId": client_order_id(
            symbol, "SELL", "testnet_tp", tp_s, qty_s, bucket_seconds=1
        ),
        "belowClientOrderId": client_order_id(
            symbol, "SELL", "testnet_sl", stop_s, qty_s, bucket_seconds=1
        ),
    }


def _query_order(client: SpotTestnetClient, symbol: str, client_id: str) -> dict[str, Any]:
    return client.signed(
        "GET",
        "/api/v3/order",
        {"symbol": symbol, "origClientOrderId": client_id},
    )


def _submit_market_buy(
    client: SpotTestnetClient,
    journal: OrderJournal,
    params: dict[str, str],
) -> dict[str, Any]:
    client_id = params["newClientOrderId"]
    journal.prepare(
        client_order_id=client_id,
        symbol=params["symbol"],
        side="BUY",
        purpose="testnet_market",
        order_type="MARKET",
        quantity=params["quoteOrderQty"],
        price="MARKET",
    )
    try:
        response = client.signed("POST", "/api/v3/order", params)
    except requests.RequestException as exc:
        journal.mark_unknown(client_id, exc)
        try:
            response = _query_order(client, params["symbol"], client_id)
        except requests.RequestException:
            raise RuntimeError(f"uncertain Testnet MARKET BUY: {client_id}") from exc
    response.setdefault("clientOrderId", client_id)
    updated = journal.record_exchange_order(client_id, response)
    if updated.state != "FILLED":
        response = _query_order(client, params["symbol"], client_id)
        updated = journal.record_exchange_order(client_id, response)
    if updated.state != "FILLED" or decimal(updated.executed_qty) <= 0:
        raise RuntimeError(f"Testnet MARKET BUY not filled: state={updated.state}")
    return response


def _submit_oco(
    client: SpotTestnetClient,
    journal: OrderJournal,
    params: dict[str, str],
    parent_client_order_id: str,
) -> dict[str, Any]:
    list_client_id = params["listClientOrderId"]
    journal.prepare(
        client_order_id=list_client_id,
        parent_client_order_id=parent_client_order_id,
        symbol=params["symbol"],
        side="SELL",
        purpose=f"testnet_oco:{parent_client_order_id[:10]}",
        order_type="OCO",
        quantity=params["quantity"],
        price=params["abovePrice"],
        metadata={
            "belowStopPrice": params["belowStopPrice"],
            "belowPrice": params["belowPrice"],
        },
    )
    journal.mark_protection_pending(parent_client_order_id)
    try:
        response = client.signed("POST", "/api/v3/orderList/oco", params)
    except requests.RequestException as exc:
        journal.mark_unknown(list_client_id, exc)
        try:
            response = client.signed(
                "GET", "/api/v3/orderList", {"origClientOrderId": list_client_id}
            )
        except requests.RequestException:
            raise RuntimeError(f"uncertain Testnet OCO submission: {list_client_id}") from exc
    order_list_id = response.get("orderListId")
    if order_list_id is None:
        response = client.signed(
            "GET", "/api/v3/orderList", {"origClientOrderId": list_client_id}
        )
        order_list_id = response.get("orderListId")
    if order_list_id is None:
        raise RuntimeError("Testnet OCO response has no orderListId")
    try:
        verified = client.signed(
            "GET", "/api/v3/orderList", {"orderListId": order_list_id}
        )
    except requests.RequestException:
        try:
            client.signed(
                "DELETE",
                "/api/v3/orderList",
                {"symbol": params["symbol"], "orderListId": order_list_id},
            )
        except requests.RequestException:
            pass
        raise
    if verified.get("listStatusType") not in ("EXEC_STARTED", "ALL_DONE"):
        try:
            client.signed(
                "DELETE",
                "/api/v3/orderList",
                {"symbol": params["symbol"], "orderListId": order_list_id},
            )
        except requests.RequestException:
            pass
        raise RuntimeError(f"Testnet OCO verification failed: {verified}")
    def cancel_unverified() -> None:
        try:
            client.signed(
                "DELETE",
                "/api/v3/orderList",
                {"symbol": params["symbol"], "orderListId": order_list_id},
            )
        except requests.RequestException:
            pass

    order_refs = verified.get("orders") or []
    if len(order_refs) != 2:
        cancel_unverified()
        raise RuntimeError("Testnet OCO verification did not return exactly two legs")
    try:
        leg_payloads = [
            client.signed(
                "GET",
                "/api/v3/order",
                {"symbol": params["symbol"], "orderId": ref["orderId"]},
            )
            for ref in order_refs
        ]
    except (KeyError, requests.RequestException) as exc:
        cancel_unverified()
        raise RuntimeError("Testnet OCO leg query failed") from exc
    if any(str(leg.get("side") or "").upper() != "SELL" for leg in leg_payloads):
        cancel_unverified()
        raise RuntimeError("Testnet OCO contains a non-SELL leg")
    leg_types = {str(leg.get("type") or "").upper() for leg in leg_payloads}
    if not ({"LIMIT_MAKER", "LIMIT"} & leg_types) or not (
        {"STOP_LOSS_LIMIT", "STOP_LOSS"} & leg_types
    ):
        cancel_unverified()
        raise RuntimeError(f"Testnet OCO leg types are invalid: {sorted(leg_types)}")
    verified["verifiedLegTypes"] = sorted(leg_types)
    journal.record_order_list(list_client_id, verified)
    journal.mark_protected(
        parent_client_order_id=parent_client_order_id,
        protection_client_order_id=list_client_id,
        order_list_id=int(order_list_id),
    )
    return verified


def execute_buy_oco_lifecycle(
    *,
    client: SpotTestnetClient,
    symbol: str,
    exchange_info: dict[str, Any],
    account_before: dict[str, Any],
    notional_usdt: object,
    max_notional_usdt: object,
    reserve_usdt: object,
    take_profit_pct: object,
    stop_loss_pct: object,
    stop_limit_offset_pct: object,
    journal_path: str | Path,
    restart_drill: bool = False,
) -> dict[str, Any]:
    rules = symbol_rules(exchange_info)
    base_asset, quote_asset = symbol_assets(exchange_info)
    if quote_asset != "USDT":
        raise RuntimeError("BUY/OCO smoke currently supports only USDT quote symbols")
    requested = decimal(notional_usdt)
    maximum = decimal(max_notional_usdt)
    reserve = decimal(reserve_usdt)
    minimum_safe = rules["min_notional"] * Decimal("1.20")
    if requested < minimum_safe:
        raise RuntimeError(f"BUY/OCO notional must be at least {minimum_safe} USDT")
    if requested > maximum:
        raise RuntimeError("BUY/OCO notional exceeds the configured maximum")
    quote_free = balance_amount(account_before, quote_asset)
    if quote_free - requested < reserve:
        raise RuntimeError(
            f"Testnet {quote_asset} reserve would be violated: free={quote_free}, reserve={reserve}"
        )
    initial_base_free = balance_amount(account_before, base_asset)
    initial_base_locked = balance_amount(account_before, base_asset, "locked")
    journal = OrderJournal(journal_path, venue="testnet")
    buy_params = build_market_buy(symbol, requested)
    buy_client_id = buy_params["newClientOrderId"]
    buy: dict[str, Any] | None = None
    oco: dict[str, Any] | None = None
    cleanup_sell: dict[str, Any] | None = None
    cleanup_errors: list[str] = []
    try:
        buy = _submit_market_buy(client, journal, buy_params)
        if restart_drill:
            journal = OrderJournal(journal_path, venue="testnet")
            persisted = journal.get(buy_client_id)
            if persisted is None or persisted.state != "FILLED":
                raise RuntimeError("restart drill could not reload FILLED BUY intent")
            reconciled = _query_order(client, symbol, buy_client_id)
            journal.record_exchange_order(buy_client_id, reconciled)

        account_after_buy = client.signed("GET", "/api/v3/account")
        executed = decimal(buy.get("executedQty") or "0")
        acquired_free = max(
            Decimal("0"), balance_amount(account_after_buy, base_asset) - initial_base_free
        )
        sellable = round_step(min(executed, acquired_free), rules["step"], "floor")
        ticker = client.public_get("/api/v3/ticker/price", {"symbol": symbol})
        oco_params = build_oco_sell(
            symbol=symbol,
            quantity=sellable,
            market_price=ticker["price"],
            rules=rules,
            parent_client_order_id=buy_client_id,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            stop_limit_offset_pct=stop_limit_offset_pct,
        )
        oco = _submit_oco(client, journal, oco_params, buy_client_id)
        return {
            "market_buy": "filled",
            "buy_client_order_id": buy_client_id,
            "buy_order_id": buy.get("orderId"),
            "executed_qty": str(executed),
            "oco": "verified",
            "oco_client_order_id": oco_params["listClientOrderId"],
            "order_list_id": oco.get("orderListId"),
            "verified_oco_leg_types": oco.get("verifiedLegTypes"),
            "restart_reconciled": restart_drill,
        }
    finally:
        if oco and oco.get("orderListId") is not None:
            try:
                client.signed(
                    "DELETE",
                    "/api/v3/orderList",
                    {"symbol": symbol, "orderListId": oco["orderListId"]},
                )
            except requests.RequestException as exc:
                try:
                    canceled_state = client.signed(
                        "GET",
                        "/api/v3/orderList",
                        {"orderListId": oco["orderListId"]},
                    )
                except requests.RequestException:
                    canceled_state = None
                if not isinstance(canceled_state, dict) or canceled_state.get(
                    "listStatusType"
                ) != "ALL_DONE":
                    cleanup_errors.append(f"OCO cancel failed: {exc}")
        if buy:
            try:
                account_cleanup = client.signed("GET", "/api/v3/account")
                acquired_free = max(
                    Decimal("0"), balance_amount(account_cleanup, base_asset) - initial_base_free
                )
                sell_qty = round_step(acquired_free, rules["step"], "floor")
                ticker = client.public_get("/api/v3/ticker/price", {"symbol": symbol})
                if sell_qty >= rules["min_qty"] and sell_qty * decimal(ticker["price"]) >= rules["min_notional"]:
                    qty_s = format_step(sell_qty, rules["step"])
                    cleanup_client_id = client_order_id(
                        symbol, "SELL", "testnet_cleanup", "MARKET", qty_s, bucket_seconds=1
                    )
                    cleanup_params = {
                        "symbol": symbol,
                        "side": "SELL",
                        "type": "MARKET",
                        "quantity": qty_s,
                        "newOrderRespType": "FULL",
                        "newClientOrderId": cleanup_client_id,
                    }
                    journal.prepare(
                        client_order_id=cleanup_client_id,
                        parent_client_order_id=buy_client_id,
                        symbol=symbol,
                        side="SELL",
                        purpose="testnet_cleanup",
                        order_type="MARKET",
                        quantity=qty_s,
                        price="MARKET",
                    )
                    try:
                        cleanup_sell = client.signed(
                            "POST", "/api/v3/order", cleanup_params
                        )
                    except requests.RequestException as exc:
                        journal.mark_unknown(cleanup_client_id, exc)
                        try:
                            cleanup_sell = _query_order(
                                client, symbol, cleanup_client_id
                            )
                        except requests.RequestException:
                            raise RuntimeError(
                                f"uncertain cleanup SELL: {cleanup_client_id}"
                            ) from exc
                    cleanup_sell.setdefault("clientOrderId", cleanup_client_id)
                    cleanup_state = journal.record_exchange_order(
                        cleanup_client_id, cleanup_sell
                    )
                    if cleanup_state.state != "FILLED":
                        cleanup_sell = _query_order(client, symbol, cleanup_client_id)
                        cleanup_state = journal.record_exchange_order(
                            cleanup_client_id, cleanup_sell
                        )
                    if cleanup_state.state != "FILLED":
                        raise RuntimeError(
                            f"cleanup SELL not filled: {cleanup_state.state}"
                        )
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                cleanup_errors.append(f"position cleanup failed: {exc}")
        if buy:
            try:
                initial_total = initial_base_free + initial_base_locked
                residual = Decimal("0")
                for attempt in range(5):
                    final_account = client.signed("GET", "/api/v3/account")
                    final_total = (
                        balance_amount(final_account, base_asset)
                        + balance_amount(final_account, base_asset, "locked")
                    )
                    residual = final_total - initial_total
                    if residual <= rules["step"]:
                        break
                    if attempt < 4:
                        time.sleep(0.25)
                if residual > rules["step"]:
                    cleanup_errors.append(
                        f"residual {base_asset} exposure after cleanup: {residual}"
                    )
            except requests.RequestException as exc:
                cleanup_errors.append(f"final balance verification failed: {exc}")
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))


def run_circuit_drill(drill_dir: str | Path) -> dict[str, Any]:
    root = Path(drill_dir)
    root.mkdir(parents=True, exist_ok=True)
    limits = RiskLimits(
        max_daily_loss_usdt=Decimal("10"),
        max_start_drawdown_pct=Decimal("0.10"),
        max_peak_drawdown_pct=Decimal("0.10"),
        portfolio_cap_usdt=Decimal("1000"),
        daily_turnover_cap_usdt=Decimal("1000"),
        daily_trade_count_cap=100,
        daily_buy_cap_usdt=Decimal("1000"),
        open_order_count_cap=100,
        correlated_cap_usdt=Decimal("1000"),
        reserve_usdt=Decimal("0"),
        max_consecutive_losses=10,
        cooldown_sec=60,
        halt_file=root / "circuit_halt.json",
        state_file=root / "risk_state.json",
        alerts_file=root / "risk_alerts.ndjson",
    )
    for path in (limits.halt_file, limits.state_file, limits.alerts_file):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    healthy = RiskSnapshot(
        equity_usdt=Decimal("100"),
        exposure_usdt=Decimal("0"),
        free_usdt=Decimal("100"),
    )
    loss = RiskSnapshot(
        equity_usdt=Decimal("89"),
        exposure_usdt=Decimal("0"),
        free_usdt=Decimal("89"),
    )
    manager = RiskManager(limits)
    if manager.evaluate(healthy, now=1_800_000_000).halted:
        raise RuntimeError("circuit drill started halted")
    tripped = manager.evaluate(loss, now=1_800_000_010)
    if not tripped.halted or not limits.halt_file.exists():
        raise RuntimeError("circuit drill did not create persistent halt")
    restarted = RiskManager(limits).evaluate(healthy, now=1_800_000_020)
    if not restarted.halted:
        raise RuntimeError("circuit halt did not survive manager restart")
    RiskManager(limits).reset(force=True, now=1_800_000_030)
    if limits.halt_file.exists():
        raise RuntimeError("manual circuit reset did not remove halt marker")
    return {
        "circuit_drill": "passed",
        "halt_survived_restart": True,
        "manual_reset_verified": True,
        "trip_reasons": list(tripped.reasons),
        "drill_dir": str(root),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    base = os.getenv("BINANCE_TESTNET_API_BASE", DEFAULT_BASE)
    client = SpotTestnetClient(
        base,
        os.getenv("BINANCE_TESTNET_API_KEY", ""),
        os.getenv("BINANCE_TESTNET_API_SECRET", ""),
    )
    t0 = int(time.time() * 1000)
    server = client.public_get("/api/v3/time")
    t1 = int(time.time() * 1000)
    clock = assess_exchange_clock(
        server_time_ms=int(server["serverTime"]),
        request_started_ms=t0,
        response_finished_ms=t1,
        max_offset_ms=1000,
        max_round_trip_ms=5000,
    )
    clock.require_safe()
    exchange_info = client.public_get("/api/v3/exchangeInfo", {"symbol": args.symbol})
    rules = symbol_rules(exchange_info)
    ticker = client.public_get("/api/v3/ticker/price", {"symbol": args.symbol})
    result: dict[str, Any] = {
        "venue": "spot-testnet",
        "base_url": client.base_url,
        "symbol": args.symbol,
        "server_time": int(server["serverTime"]),
        "clock_offset_ms": clock.offset_ms,
        "clock_round_trip_ms": clock.round_trip_ms,
        "clock_guaranteed_offset_ms": clock.guaranteed_offset_ms,
        "filters": {name: str(value) for name, value in rules.items()},
        "mode": args.mode,
    }
    if args.mode == "public":
        return result
    if args.mode == "circuit-drill":
        result.update(run_circuit_drill(args.drill_dir))
        return result

    account = client.signed("GET", "/api/v3/account")
    if account.get("canTrade") is not True:
        raise RuntimeError("Testnet account cannot trade")
    open_orders = client.signed("GET", "/api/v3/openOrders", {"symbol": args.symbol})
    result["authenticated"] = True
    result["open_order_count"] = len(open_orders)
    if args.mode == "authenticated":
        return result

    if args.mode in ("buy-oco", "buy-oco-restart"):
        if os.getenv("BOT_TESTNET_BUY_OCO_CONFIRMED", "") != "YES":
            raise RuntimeError(
                f"{args.mode} requires BOT_TESTNET_BUY_OCO_CONFIRMED=YES"
            )
        lifecycle = execute_buy_oco_lifecycle(
            client=client,
            symbol=args.symbol,
            exchange_info=exchange_info,
            account_before=account,
            notional_usdt=args.notional_usdt,
            max_notional_usdt=args.max_notional_usdt,
            reserve_usdt=args.reserve_usdt,
            take_profit_pct=args.take_profit_pct,
            stop_loss_pct=args.stop_loss_pct,
            stop_limit_offset_pct=args.stop_limit_offset_pct,
            journal_path=args.journal,
            restart_drill=args.mode == "buy-oco-restart",
        )
        result.update(lifecycle)
        result["cleanup"] = "OCO canceled and test position flattened"
        return result

    order_params = build_non_filling_limit_buy(
        symbol=args.symbol,
        market_price=ticker["price"],
        rules=rules,
        notional_usdt=args.notional_usdt,
    )
    actual_notional = decimal(order_params["quantity"]) * decimal(order_params["price"])
    if actual_notional > decimal(args.max_notional_usdt):
        raise RuntimeError(
            f"normalized order {actual_notional} USDT exceeds --max-notional-usdt"
        )
    if args.mode == "order-test":
        client.signed("POST", "/api/v3/order/test", order_params)
        result["order_test"] = "accepted"
        result["notional_usdt"] = str(actual_notional)
        return result

    if os.getenv("BOT_TESTNET_ORDER_CONFIRMED", "") != "YES":
        raise RuntimeError("limit-cancel requires BOT_TESTNET_ORDER_CONFIRMED=YES")
    created: dict[str, Any] | None = None
    try:
        created = client.signed("POST", "/api/v3/order", order_params)
        client_id = str(created.get("clientOrderId") or order_params["newClientOrderId"])
        queried = client.signed(
            "GET",
            "/api/v3/order",
            {"symbol": args.symbol, "origClientOrderId": client_id},
        )
        canceled = client.signed(
            "DELETE",
            "/api/v3/order",
            {"symbol": args.symbol, "origClientOrderId": client_id},
        )
        result.update(
            {
                "limit_order": "created-queried-canceled",
                "client_order_id": client_id,
                "order_id": queried.get("orderId"),
                "final_status": canceled.get("status"),
                "notional_usdt": str(actual_notional),
            }
        )
        return result
    finally:
        if created:
            client_id = str(created.get("clientOrderId") or order_params["newClientOrderId"])
            try:
                client.signed(
                    "DELETE",
                    "/api/v3/order",
                    {"symbol": args.symbol, "origClientOrderId": client_id},
                )
            except requests.RequestException:
                pass


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Fail-closed Binance Spot Testnet smoke test")
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument(
        "--mode",
        choices=(
            "public",
            "authenticated",
            "order-test",
            "limit-cancel",
            "buy-oco",
            "buy-oco-restart",
            "circuit-drill",
        ),
        default="public",
    )
    parser.add_argument("--notional-usdt", type=Decimal, default=Decimal("10"))
    parser.add_argument("--max-notional-usdt", type=Decimal, default=Decimal("25"))
    parser.add_argument("--reserve-usdt", type=Decimal, default=Decimal("100"))
    parser.add_argument("--take-profit-pct", type=Decimal, default=Decimal("0.02"))
    parser.add_argument("--stop-loss-pct", type=Decimal, default=Decimal("0.02"))
    parser.add_argument(
        "--stop-limit-offset-pct", type=Decimal, default=Decimal("0.002")
    )
    parser.add_argument(
        "--journal",
        default=os.getenv(
            "BOT_TESTNET_ORDER_JOURNAL", ".runtime/testnet_order_intents.sqlite3"
        ),
    )
    parser.add_argument("--drill-dir", default=".runtime/testnet_circuit_drill")
    args = parser.parse_args()
    args.symbol = args.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol):
        parser.error("--symbol must be a valid uppercase Binance symbol")
    if args.notional_usdt <= 0 or args.max_notional_usdt <= 0:
        parser.error("notional limits must be > 0")
    if args.notional_usdt > args.max_notional_usdt:
        parser.error("--notional-usdt cannot exceed --max-notional-usdt")
    if args.reserve_usdt < 0:
        parser.error("--reserve-usdt must be >= 0")
    if not Decimal("0") < args.take_profit_pct < Decimal("0.25"):
        parser.error("--take-profit-pct must be between 0 and 0.25")
    if not Decimal("0") < args.stop_loss_pct < Decimal("0.25"):
        parser.error("--stop-loss-pct must be between 0 and 0.25")
    if not Decimal("0") < args.stop_limit_offset_pct < args.stop_loss_pct:
        parser.error("--stop-limit-offset-pct must be positive and below stop loss")
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
