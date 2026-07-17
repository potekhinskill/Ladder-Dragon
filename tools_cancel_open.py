#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.

import os, hmac, time, hashlib, argparse, urllib.parse, json, re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from product_version import user_agent

DEFAULT_MAIN = "https://api.binance.com"
DEFAULT_TEST = "https://testnet.binance.vision"

SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
ALLOWED_BASE_URLS = {DEFAULT_MAIN, DEFAULT_TEST}


def load_keys(testnet: bool):
    load_dotenv()
    if testnet:
        key = os.getenv("BINANCE_TESTNET_API_KEY") or ""
        sec = os.getenv("BINANCE_TESTNET_API_SECRET") or ""
        prefix = "BINANCE_TESTNET"
    else:
        key = os.getenv("BINANCE_API_KEY") or os.getenv("API_KEY") or ""
        sec = os.getenv("BINANCE_API_SECRET") or os.getenv("API_SECRET") or ""
        prefix = "BINANCE"
    if not key or not sec:
        raise SystemExit(
            f"[ERR] API keys not found. Put {prefix}_API_KEY / "
            f"{prefix}_API_SECRET in .env"
        )
    return key, sec

def build_session():
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=0.6,
        status_forcelist=(418, 429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "DELETE"])
    )
    s.headers.update({
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": user_agent("cancel-open")
    })
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

def exchange_time_ms(session, base_url):
    try:
        r = session.get(base_url.rstrip("/") + "/api/v3/time", timeout=10)
        r.raise_for_status()
        return int(r.json().get("serverTime", 0))
    except Exception:
        return 0

def sign_params(params, secret):
    query = urllib.parse.urlencode(params, doseq=True)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig

def _retry_after_sleep_if_any(resp):
    if resp is None:
        return
    if resp.status_code in (418, 429):
        ra = resp.headers.get("Retry-After")
        if ra and ra.isdigit():
            sleep_s = min(int(ra), 5)
            if sleep_s > 0:
                time.sleep(sleep_s)

def b_request(session, method, base_url, path, params=None, key=None, secret=None,
              signed=True, timeout=15, recv_window=5000, ts_offset_ms=0, _retry1021=True):
    params = dict(params or {})
    headers = {"X-MBX-APIKEY": key} if key else {}
    url = base_url.rstrip("/") + path

    data = None
    if signed:
        params["timestamp"] = int(time.time() * 1000) + int(ts_offset_ms)
        params["recvWindow"] = int(recv_window)
        qs = sign_params(params, secret)
        if method == "GET":
            url = url + "?" + qs
        else:
            data = qs
    else:
        if method == "GET":
            url = url + "?" + urllib.parse.urlencode(params, doseq=True)
        else:
            data = urllib.parse.urlencode(params, doseq=True)

    try:
        resp = session.request(method, url, headers=headers, data=data, timeout=timeout)
    except requests.RequestException as e:
        raise requests.HTTPError(f"[NET] {e.__class__.__name__}: {e}") from e

    txt = resp.text
    if resp.status_code >= 400:
        try:
            j = resp.json()
            code = j.get("code")
            msg = j.get("msg")
            if code == -1021 and _retry1021 and signed:
                new_server = exchange_time_ms(session, base_url)
                if new_server:
                    local = int(time.time() * 1000)
                    new_offset = new_server - local
                    return b_request(session, method, base_url, path, params, key, secret,
                                     signed, timeout, recv_window, new_offset, _retry1021=False)
            _retry_after_sleep_if_any(resp)
            raise requests.HTTPError(f"HTTP {resp.status_code} binance_code={code} msg={msg} body={txt}")
        except ValueError:
            _retry_after_sleep_if_any(resp)
            raise requests.HTTPError(f"HTTP {resp.status_code}: {txt}")

    try:
        return resp.json()
    except ValueError:
        raise requests.HTTPError(f"[ERR] Non-JSON response: {txt[:200]}")

def fetch_open_orders(session, base_url, symbol, key, secret, **kw):
    return b_request(session, "GET", base_url, "/api/v3/openOrders",
                     {"symbol": symbol}, key, secret, signed=True, **kw)

def fetch_open_oco_lists(session, base_url, symbol, key, secret, **kw):
    lst = b_request(session, "GET", base_url, "/api/v3/openOrderList",
                    {}, key, secret, signed=True, **kw)
    out = []
    for oc in lst:
        sym = oc.get("symbol") or oc.get("listSymbol")
        if not sym:
            # подстраховка: взять из дочернего ордера
            orders = oc.get("orders") or oc.get("orderReports") or []
            if orders:
                sym = orders[0].get("symbol")
        if (not symbol) or sym == symbol:
            out.append(oc)
    return out

def cancel_order(session, base_url, symbol, order_id, key, secret, **kw):
    return b_request(session, "DELETE", base_url, "/api/v3/order",
                     {"symbol": symbol, "orderId": order_id}, key, secret, signed=True, **kw)

def cancel_oco(session, base_url, symbol, order_list_id, key, secret, **kw):
    return b_request(session, "DELETE", base_url, "/api/v3/orderList",
                     {"symbol": symbol, "orderListId": order_list_id}, key, secret, signed=True, **kw)

def fmt_qty(x: float) -> str:
    s = f"{x:.16f}".rstrip("0").rstrip(".")
    return s if s else "0"

def safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

def parse_args():
    p = argparse.ArgumentParser(description="Cancel open spot orders (and OCO) on Binance")
    p.add_argument("--pairs", nargs="+", required=True, help="Symbols, e.g. SOLUSDT ETHUSDT")
    p.add_argument("--sides", choices=["BUY", "SELL", "BOTH"], default="BOTH")
    p.add_argument("--types", choices=["LIMIT", "OCO", "BOTH"], default="BOTH")
    p.add_argument("--min-age-sec", type=int, default=0,
                   help="Cancel only orders older than N seconds (creation/transaction time)")
    p.add_argument("--live", action="store_true", help="Execute real cancels (default: dry-run)")
    p.add_argument("--recv-window", type=int, default=int(os.getenv("BINANCE_RECV_WINDOW", "5000")))
    p.add_argument("--base-url", default=None,
                   help="Explicit HTTPS Binance endpoint; custom hosts require BOT_ALLOW_CUSTOM_BINANCE_BASE=YES")
    venue = p.add_mutually_exclusive_group()
    venue.add_argument("--testnet", dest="testnet", action="store_true", default=True,
                       help="Use Binance Spot Testnet (default)")
    venue.add_argument("--mainnet", dest="testnet", action="store_false",
                       help="Use Binance Mainnet")
    args = p.parse_args()
    if args.min_age_sec < 0:
        p.error("--min-age-sec must be >= 0")
    if not 1000 <= args.recv_window <= 60000:
        p.error("--recv-window must be between 1000 and 60000")
    normalized = []
    for symbol in args.pairs:
        symbol = symbol.strip().upper()
        if not SYMBOL_RE.fullmatch(symbol):
            p.error(f"invalid Binance symbol: {symbol!r}")
        normalized.append(symbol)
    args.pairs = normalized
    default_base = DEFAULT_TEST if args.testnet else DEFAULT_MAIN
    args.base_url = (args.base_url or default_base).rstrip("/")
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
        p.error("--base-url must be an HTTPS origin without a path")
    if (
        args.base_url not in ALLOWED_BASE_URLS
        and os.getenv("BOT_ALLOW_CUSTOM_BINANCE_BASE", "") != "YES"
    ):
        p.error("custom --base-url requires BOT_ALLOW_CUSTOM_BINANCE_BASE=YES")
    if args.live and os.getenv("BOT_LIVE_CONFIRMED", "") != "YES":
        p.error("--live requires BOT_LIVE_CONFIRMED=YES")
    if (
        args.live
        and not args.testnet
        and os.getenv("BOT_MAINNET_CANCEL_CONFIRMED", "") != "YES"
    ):
        p.error(
            "Mainnet cancellation requires BOT_MAINNET_CANCEL_CONFIRMED=YES"
        )
    return args

def is_unknown_2011(err: Exception) -> bool:
    s = str(err)
    return ("2011" in s) or ("Unknown order sent" in s) or ("Order does not exist" in s)

def main():
    args = parse_args()
    key, sec = load_keys(args.testnet)
    DRY = not args.live
    base_url = args.base_url
    print(
        "[CONFIG] "
        f"venue={'testnet' if args.testnet else 'mainnet'} "
        f"mode={'DRY' if DRY else 'LIVE'} pairs={','.join(args.pairs)} "
        f"sides={args.sides} types={args.types} min_age_sec={args.min_age_sec}"
    )

    session = build_session()

    # Биржевое "сейчас" для корректного возраста ордеров
    server_ms = exchange_time_ms(session, base_url)
    local_ms  = int(time.time() * 1000)
    ts_offset_ms = (server_ms - local_ms) if server_ms else 0
    now_ms = local_ms + ts_offset_ms

    # Возрастной фильтр (сек → мс)
    min_age_sec = getattr(args, "min_age_sec", 0)
    min_age_ms = max(0, int(min_age_sec) * 1000)

    total_would_cancel = 0
    total_live_canceled = 0
    total_already_closed = 0
    total_errors = 0

    for symbol in args.pairs:
        # ===== LIMIT =====
        if args.types in ("LIMIT", "BOTH"):
            try:
                oo = fetch_open_orders(
                    session, base_url, symbol, key, sec,
                    recv_window=args.recv_window, ts_offset_ms=ts_offset_ms
                )
            except Exception as e:
                print(f"[ERR] fetch open orders {symbol}: {e}")
                oo = []

            for o in oo:
                side = o.get("side")
                o_type = o.get("type")
                if not side or o_type != "LIMIT":
                    continue
                if args.sides != "BOTH" and side != args.sides:
                    continue

                # возраст ордера
                created_ms = safe_int(o.get("time") or o.get("transactTime") or o.get("updateTime"))
                age_ms = (now_ms - created_ms) if created_ms else None
                if min_age_ms and (age_ms is None or age_ms < min_age_ms):
                    print(f"[SKIP-age] {symbol} {side} LIMIT id={o.get('orderId')} "
                          f"age={(age_ms//1000) if age_ms is not None else 'n/a'}s < {min_age_ms//1000}s")
                    continue

                price = safe_float(o.get("price"))
                qty   = safe_float(o.get("origQty"))

                if DRY:
                    total_would_cancel += 1
                    print(f"[DRY] cancel {symbol} {side} LIMIT id={o['orderId']} price={price} qty={fmt_qty(qty)}")
                else:
                    try:
                        cancel_order(
                            session, base_url, symbol, o["orderId"], key, sec,
                            recv_window=args.recv_window, ts_offset_ms=ts_offset_ms
                        )
                        total_live_canceled += 1
                        print(f"[OK] cancel {symbol} {side} LIMIT id={o['orderId']}")
                    except Exception as he:
                        if is_unknown_2011(he):
                            print(f"[OK-ALREADY] {symbol} {side} LIMIT id={o['orderId']} already closed")
                            total_already_closed += 1
                        else:
                            total_errors += 1
                            print(f"[ERR] cancel order {symbol} id={o['orderId']}: {he}")
                            print(f"[ERR]    {symbol} {side} LIMIT id={o['orderId']} price={price} qty={fmt_qty(qty)}  -> failed")

        # ===== OCO =====
        if args.types in ("OCO", "BOTH"):
            try:
                oc = fetch_open_oco_lists(
                    session, base_url, symbol, key, sec,
                    recv_window=args.recv_window, ts_offset_ms=ts_offset_ms
                )
            except Exception as e:
                print(f"[ERR] fetch open oco {symbol}: {e}")
                oc = []

            for o in oc:
                o_id = o.get("orderListId")
                side = o.get("side", "SELL")
                if args.sides not in ("BOTH", side):
                    continue

                # возраст OCO (по transactionTime списка)
                created_ms = safe_int(o.get("transactionTime"))
                age_ms = (now_ms - created_ms) if created_ms else None
                if min_age_ms and (age_ms is None or age_ms < min_age_ms):
                    print(f"[SKIP-age] OCO {symbol} id={o_id} "
                          f"age={(age_ms//1000) if age_ms is not None else 'n/a'}s < {min_age_ms//1000}s")
                    continue

                if DRY:
                    total_would_cancel += 1
                    print(f"[DRY] cancel OCO {symbol} id={o_id}")
                else:
                    try:
                        cancel_oco(
                            session, base_url, symbol, o_id, key, sec,
                            recv_window=args.recv_window, ts_offset_ms=ts_offset_ms
                        )
                        total_live_canceled += 1
                        print(f"[OK] cancel OCO {symbol} id={o_id}")
                    except Exception as he:
                        if is_unknown_2011(he):
                            print(f"[OK-ALREADY] {symbol} OCO id={o_id} already closed")
                            total_already_closed += 1
                        else:
                            total_errors += 1
                            print(f"[ERR] cancel OCO {symbol} id={o_id}: {he}")

    if DRY:
        print(f"[DONE-DRY] Would cancel: {total_would_cancel} items")
    else:
        print(f"[DONE] Canceled: {total_live_canceled} | Already-closed: {total_already_closed} | Errors: {total_errors}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INT] Interrupted by user")
