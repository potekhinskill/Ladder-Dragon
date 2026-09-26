#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compare BNB commission rows with authenticated exchange history without writes.
"""Aggregate-only diagnostic. No import, repair, evidence export, or replay admission."""

import argparse
from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

import requests

from ladder_dragon.dashboard.services.binance_readonly import ReadOnlyBinanceClient
from ladder_dragon.execution.exchange_evidence import checked_trade, exact_nonnegative, valid_exchange_name
from ladder_dragon.execution.market_http_body import read_body
from ladder_dragon.execution.order_fill_evidence import complete_fills, terminal_order


class ProbeSession(requests.Session):
    """Count all HTTP attempts, including clock reads and client retries."""

    def __init__(self, maximum_requests, *, verify_orders=False):
        super().__init__()
        self.maximum_requests = maximum_requests
        self.calls = 0
        self.deadline = time.monotonic() + 180
        self.trust_env = False
        self.verify_orders = verify_orders

    def request(self, method, url, **kwargs):
        allowed = {
            "https://api.binance.com/api/v3/time", "https://api.binance.com/api/v3/myTrades",
        }
        if self.verify_orders:
            allowed.add("https://api.binance.com/api/v3/order")
        if method != "GET" or url not in allowed:
            raise RuntimeError("PROBE_ENDPOINT_FORBIDDEN")
        remaining = self.deadline - time.monotonic()
        if self.calls >= self.maximum_requests or remaining <= 0:
            raise RuntimeError("PROBE_BUDGET_EXHAUSTED")
        self.calls += 1
        kwargs.update(allow_redirects=False, stream=True, timeout=min(5, remaining))
        response = super().request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise RuntimeError("PROBE_REDIRECT_REJECTED")
        return response


class ProbeClient(ReadOnlyBinanceClient):
    def _payload(self, response, *, endpoint):
        try:
            raw = read_body(response, deadline=min(self._session.deadline, time.monotonic()+5), max_bytes=65536)
            return json.loads(raw)
        finally:
            response.close()


def selected_rows(path, maximum_rows):
    """Close the read transaction before any exchange request."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as con:
        con.execute("PRAGMA query_only=ON")
        con.row_factory = sqlite3.Row
        rows = [dict(row) for row in con.execute(
            "SELECT symbol,side,price_text,gross_qty,ts,trade_id,commission_asset,commission_amount "
            "FROM trades WHERE commission_asset='BNB' ORDER BY symbol,trade_id LIMIT ?",
            (maximum_rows+1,),
        )]
    if len(rows) > maximum_rows:
        raise ValueError("PROBE_ROW_CAPACITY")
    identities = set()
    for row in rows:
        identity = (row["symbol"], row["trade_id"])
        if (not valid_exchange_name(row["symbol"]) or type(row["trade_id"]) is not int
                or row["trade_id"] < 0 or type(row["ts"]) is not int or row["ts"] <= 0
                or row["side"] not in {"BUY", "SELL"} or identity in identities):
            raise ValueError("PROBE_LOCAL_IDENTITY_INVALID")
        identities.add(identity)
        for field in ("price_text", "gross_qty", "commission_amount"):
            number = exact_nonnegative(row[field])
            if field != "commission_amount" and number <= 0:
                raise ValueError("PROBE_LOCAL_AMOUNT_INVALID")
    return rows


def complete_order(client, symbol, order_id):
    """Require terminal identity, unique fills, and exact executed totals."""
    order = client.signed("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, timeout=5)
    terminal_order(order, symbol, order_id)
    fills = client.signed("GET", "/api/v3/myTrades", {"symbol": symbol, "orderId": order_id, "limit": 1000}, timeout=5)
    return complete_fills(order, fills, symbol, order_id)


def verify_rows(rows, client, *, verify_orders=False):
    counts = Counter(selected=len(rows), checked=0, matched=0, missing=0, mismatched=0)
    orders = {}
    for row in rows:
        payload = client.signed("GET", "/api/v3/myTrades", {
            "symbol": row["symbol"], "fromId": row["trade_id"], "limit": 1,
        }, timeout=5)
        if not isinstance(payload, list) or len(payload) > 1:
            raise ValueError("PROBE_EXCHANGE_COLLECTION_INVALID")
        counts["checked"] += 1
        if not payload:
            counts["missing"] += 1
            continue
        trade = payload[0]
        price, qty, fee = checked_trade(trade, row["symbol"])
        if trade["id"] != row["trade_id"]:
            counts["missing"] += 1
            continue
        matches = (
            trade["time"] == row["ts"] and ("BUY" if trade["isBuyer"] else "SELL") == row["side"]
            and trade["commissionAsset"] == row["commission_asset"]
            and price == exact_nonnegative(row["price_text"])
            and qty == exact_nonnegative(row["gross_qty"])
            and fee == exact_nonnegative(row["commission_amount"])
        )
        counts["matched" if matches else "mismatched"] += 1
        if matches and verify_orders:
            key = (row["symbol"], trade["orderId"])
            if key not in orders:
                orders[key] = complete_order(client, *key)
            member = orders[key].get(trade["id"])
            fields = ("symbol", "orderId", "id", "time", "isBuyer", "price", "qty", "quoteQty", "commission", "commissionAsset")
            if member is None or any(member.get(k) != trade.get(k) for k in fields):
                raise ValueError("PROBE_FILL_CHANGED_BETWEEN_READS")
    if verify_orders:
        counts["complete_orders"] = len(orders)
    return dict(counts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats-db", type=Path, required=True)
    parser.add_argument("--maximum-rows", type=int, default=100)
    parser.add_argument("--maximum-requests", type=int, default=100)
    parser.add_argument("--verify-orders", action="store_true")
    args = parser.parse_args(argv)
    report = dict(status="BLOCKED", database_written=False, replay_allowed=False)
    session = None
    try:
        if not 1 <= args.maximum_rows <= 100 or not 1 <= args.maximum_requests <= (300 if args.verify_orders else 100):
            raise ValueError("PROBE_LIMIT_INVALID")
        rows = selected_rows(args.stats_db, args.maximum_rows)
        if not rows:
            raise ValueError("PROBE_NO_ROWS")
        # Credentials are injected by the host; this command never reads dotenv files.
        def credentials():
            return (os.environ.get("DASHBOARD_BINANCE_API_KEY", ""),
                    os.environ.get("DASHBOARD_BINANCE_API_SECRET", ""))
        if not all(credentials()):
            raise RuntimeError("PROBE_READONLY_CREDENTIALS_UNAVAILABLE")
        session = ProbeSession(args.maximum_requests, verify_orders=args.verify_orders)
        client = ProbeClient(session=session, base_url="https://api.binance.com",
                             credentials=credentials, auth_error=lambda **kwargs: None)
        counts = verify_rows(rows, client, verify_orders=True) if args.verify_orders else verify_rows(rows, client)
        report.update(counts)
        report["status"] = "MATCHED_NOT_REPLAY_READY" if counts["matched"] == len(rows) else "MISMATCH_OR_MISSING"
        if args.verify_orders and counts["matched"] == len(rows):
            report["status"] = "COMPLETE_ORDERS_NOT_REPLAY_READY"
    except (OSError, TypeError, ValueError, RuntimeError, sqlite3.Error, requests.RequestException) as error:
        # Never expose an exception chain, signed URL, provider payload, or row identity.
        report["reason"] = "PROBE_FAILED_CLOSED"
        report["error_type"] = type(error).__name__
    finally:
        if session is not None:
            report["http_attempts"] = session.calls
            session.close()
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"MATCHED_NOT_REPLAY_READY", "COMPLETE_ORDERS_NOT_REPLAY_READY"} else 2
