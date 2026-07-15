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
import re
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from exchange_math import decimal, normalized_order_values
from order_identity import client_order_id
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

    account = client.signed("GET", "/api/v3/account")
    if account.get("canTrade") is not True:
        raise RuntimeError("Testnet account cannot trade")
    open_orders = client.signed("GET", "/api/v3/openOrders", {"symbol": args.symbol})
    result["authenticated"] = True
    result["open_order_count"] = len(open_orders)
    if args.mode == "authenticated":
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
    parser = argparse.ArgumentParser(description="Fail-closed Binance Spot Testnet smoke test")
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument(
        "--mode",
        choices=("public", "authenticated", "order-test", "limit-cancel"),
        default="public",
    )
    parser.add_argument("--notional-usdt", type=Decimal, default=Decimal("10"))
    parser.add_argument("--max-notional-usdt", type=Decimal, default=Decimal("25"))
    args = parser.parse_args()
    args.symbol = args.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol):
        parser.error("--symbol must be a valid uppercase Binance symbol")
    if args.notional_usdt <= 0 or args.max_notional_usdt <= 0:
        parser.error("notional limits must be > 0")
    if args.notional_usdt > args.max_notional_usdt:
        parser.error("--notional-usdt cannot exceed --max-notional-usdt")
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
