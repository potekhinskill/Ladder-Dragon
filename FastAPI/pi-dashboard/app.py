# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение: локальный read-only dashboard; торговые ключи и ордера сюда не передаются.

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
# убрали requests из общего импорта:
import psutil, shutil, json, os, socket, asyncio, subprocess, math, time, hmac, hashlib, secrets, threading, re
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path
import sqlite3
from typing import List, Dict, Optional, Tuple

from ladder_dragon.ai.ai_runtime_status import read_runtime_status
from ladder_dragon.ai.ai_control import read_ai_control, write_ai_control
from product_version import PRODUCT_NAME, __version__

try:
    import requests
except Exception:
    requests = None

from ladder_dragon.execution.telegram_alerts import notify_binance_auth_error

APP_TZ = ZoneInfo("Asia/Almaty")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
HIST_FILE = DATA_DIR / "metrics.ndjson"
SESSION = requests.Session() if requests else None
if SESSION:
    SESSION.headers.update({"User-Agent": "PiDashboard/1.0"})
BINANCE_BASE = os.getenv("BINANCE_API_BASE", "https://api.binance.com").rstrip("/")
DASHBOARD_AUTH_TOKEN = os.getenv("DASHBOARD_AUTH_TOKEN", "")
DASHBOARD_TRUST_PROXY_AUTH = os.getenv("DASHBOARD_TRUST_PROXY_AUTH", "0") == "1"
DASHBOARD_PROXY_AUTH_SECRET = os.getenv("DASHBOARD_PROXY_AUTH_SECRET", "")
DASHBOARD_RATE_LIMIT_PER_MIN = max(1, int(os.getenv("DASHBOARD_RATE_LIMIT_PER_MIN", "120")))
_RATE_BUCKETS: Dict[str, deque] = defaultdict(deque)
_RATE_LOCK = threading.Lock()
_BALANCE_CACHE: Dict[str, object] = {"ts": 0.0, "payload": None}
_BALANCE_CACHE_TTL_SEC = max(5.0, float(os.getenv("DASHBOARD_BALANCE_CACHE_SEC", "10")))
_BALANCE_CACHE_LOCK = threading.Lock()
_OPEN_ORDERS_CACHE: Dict[str, object] = {"ts": 0.0, "payload": None}
_OPEN_ORDERS_CACHE_TTL_SEC = max(3.0, float(os.getenv("DASHBOARD_OPEN_ORDERS_CACHE_SEC", "5")))
_OPEN_ORDERS_CACHE_LOCK = threading.Lock()
_OPS_CACHE: Dict[str, object] = {"ts": 0.0, "payload": None}
_OPS_CACHE_TTL_SEC = max(10.0, float(os.getenv("DASHBOARD_OPS_CACHE_SEC", "30")))
_OPS_CACHE_LOCK = threading.Lock()
AI_DECISIONS_DB = os.getenv("AI_DECISIONS_DB", ".runtime/ai_decisions.sqlite3")
AI_USAGE_LOG = os.getenv("AI_USAGE_LOG", ".runtime/ai_usage.ndjson")
AI_MODE = os.getenv("AI_MODE", "SHADOW").upper()
AI_DAILY_COST_LIMIT_USD = Decimal(os.getenv("AI_DAILY_COST_LIMIT_USD", "0.50"))
AI_DAILY_TOKEN_LIMIT = int(os.getenv("AI_DAILY_TOKEN_LIMIT", "500000"))
AI_MAX_REQUESTS_PER_DAY = int(os.getenv("AI_MAX_REQUESTS_PER_DAY", "1000"))
AI_ERROR_DEGRADED_WINDOW_SEC = max(
    60.0, float(os.getenv("AI_ERROR_DEGRADED_WINDOW_SEC", "900"))
)
AI_ERROR_DEGRADED_MIN = max(1, int(os.getenv("AI_ERROR_DEGRADED_MIN", "3")))
AI_RUNTIME_STATUS_FILE = Path(
    os.getenv("AI_RUNTIME_STATUS_FILE", "/run/mybot/ai_status.json")
)
AI_CONTROL_FILE = Path(
    os.getenv("AI_CONTROL_FILE", str(BASE_DIR / "data" / "ai_control.json"))
)
DASHBOARD_FOLLOW_BOT_PATHS = (
    os.getenv("DASHBOARD_FOLLOW_BOT_PATHS", "0") == "1"
)

@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(collector_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="Pi Health API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

GiB = 1024**3


@app.middleware("http")
async def authenticate_and_rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        proxy_user = request.headers.get("X-Authenticated-User", "")
        proxy_secret = request.headers.get("X-Dashboard-Proxy-Secret", "")
        bearer = request.headers.get("Authorization", "")
        header_token = request.headers.get("X-Dashboard-Token", "")
        supplied = bearer[7:] if bearer.startswith("Bearer ") else header_token
        proxy_authenticated = (
            DASHBOARD_TRUST_PROXY_AUTH
            and bool(proxy_user)
            and bool(DASHBOARD_PROXY_AUTH_SECRET)
            and secrets.compare_digest(proxy_secret, DASHBOARD_PROXY_AUTH_SECRET)
        )
        token_authenticated = (
            bool(DASHBOARD_AUTH_TOKEN) and secrets.compare_digest(supplied, DASHBOARD_AUTH_TOKEN)
        )
        authenticated = proxy_authenticated or token_authenticated
        if not authenticated:
            proxy_configured = (
                DASHBOARD_TRUST_PROXY_AUTH and bool(DASHBOARD_PROXY_AUTH_SECRET)
            )
            status = 503 if not DASHBOARD_AUTH_TOKEN and not proxy_configured else 401
            return JSONResponse({"ok": False, "error": "dashboard authentication required"}, status_code=status)

        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _RATE_LOCK:
            bucket = _RATE_BUCKETS[client]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= DASHBOARD_RATE_LIMIT_PER_MIN:
                return JSONResponse({"ok": False, "error": "rate limit exceeded"}, status_code=429)
            bucket.append(now)
    return await call_next(request)

# ---- helpers for DB trades / PnL -------------------------------------------------

def get_db_path() -> str:
    # При явном разрешении дашборд следует за фактическим venue торгового
    # процесса. Status-файл не содержит ключей и доступен только локальному user.
    runtime = _load_ai_runtime_status()
    if DASHBOARD_FOLLOW_BOT_PATHS and runtime:
        runtime_path = runtime.get("paths", {}).get("stats_db")
        if isinstance(runtime_path, str) and runtime_path.strip():
            return runtime_path.strip()
    p = os.getenv("BOT_STATS_DB", "").strip()
    if p:
        return p
    # fallback to symlink path from your systemd env
    return "/home/bot/stats/bot_stats.db"


def _load_ai_runtime_status() -> Dict:
    """Прочитать безопасный heartbeat бота, не обращаясь к /proc или его env."""
    try:
        return read_runtime_status(AI_RUNTIME_STATUS_FILE)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _runtime_data_path(runtime: Dict, name: str, fallback: str) -> Path:
    """Выбрать runtime-путь только когда это явно разрешено в dashboard env."""
    if DASHBOARD_FOLLOW_BOT_PATHS:
        value = runtime.get("paths", {}).get(name)
        if isinstance(value, str) and value.strip():
            return Path(value.strip())
    return Path(fallback)

def _open_db():
    path = get_db_path()
    con = sqlite3.connect(path, timeout=1.0)
    con.row_factory = sqlite3.Row
    return con, path

def _has_column(con: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cur = con.execute(f"PRAGMA table_info({table});")
        cols = [r["name"] for r in cur.fetchall()]
        return col in cols
    except Exception:
        return False

def _ts_to_s(ts_val) -> int:
    # supports ms and s
    try:
        ts = int(ts_val)
        return ts // 1000 if ts > 10_000_000_000 else ts
    except Exception:
        return 0

def _fee_pct_default() -> float:
    try:
        return float(os.getenv("BOT_FEE_PCT", "0.00075"))  # 0.075% по умолчанию (скидка BNB)
    except Exception:
        return 0.00075

def _estimate_fee_quote(price: float, qty: float, fee_quote: float, fee_pct: float) -> float:
    # если в БД есть fee в валюте котировки (USDT) — доверяем ему; иначе оцениваем через % (оплата BNB)
    if fee_quote and fee_quote > 0:
        return float(fee_quote)
    return float(price * qty * fee_pct)

def _load_trades(con: sqlite3.Connection, symbols: Optional[List[str]] = None) -> List[sqlite3.Row]:
    sym_filter = ""
    args: List = []
    if symbols:
        qs = ",".join("?" for _ in symbols)
        sym_filter = f" AND symbol IN ({qs})"
        args.extend(symbols)

    # fee_quote может отсутствовать на старых установках — COALESCE в 0
    sql = f"""
    SELECT
      symbol, side, price, qty,
      COALESCE(fee_quote, 0.0) AS fee_quote,
      CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
    FROM trades
    WHERE 1=1 {sym_filter}
    ORDER BY ts_s ASC
    """
    return list(con.execute(sql, args).fetchall())

def _fifo_realized_pnl(rows: List[sqlite3.Row], cutoff_s: int, fee_pct: float) -> Dict:
    """
    FIFO реализованный PnL: проходим ВСЮ историю, стык BUY-LOTов учитывает комиссию BUY,
    SELL в окне — выручка минус комиссия SELL. Реализованную прибыль считаем только для SELL в окне.
    """
    lots: Dict[str, List[Tuple[float, float]]] = {}
    realized_pnl = 0.0
    fees_in_window = 0.0
    total_trades_in_window = 0
    buy_vol = 0.0
    sell_vol = 0.0

    for r in rows:
        sym = r["symbol"]
        side = str(r["side"]).upper()
        price = float(r["price"])
        qty = float(r["qty"])
        ts_s = _ts_to_s(r["ts_s"])
        fee_q = _estimate_fee_quote(price, qty, float(r["fee_quote"]), fee_pct)

        if sym not in lots:
            lots[sym] = []

        if side == "BUY":
            cost_unit = (price * qty + fee_q) / max(qty, 1e-12)
            lots[sym].append([qty, cost_unit])
            if ts_s >= cutoff_s:
                total_trades_in_window += 1
                buy_vol += price * qty
                fees_in_window += fee_q

        elif side == "SELL":
            revenue = price * qty
            sell_fee = fee_q
            if ts_s >= cutoff_s:
                total_trades_in_window += 1
                sell_vol += revenue
                fees_in_window += sell_fee

            remain = qty
            pool = lots[sym]
            while remain > 1e-12 and pool:
                lot_qty, lot_cost_unit = pool[0]
                take = min(lot_qty, remain)
                if ts_s >= cutoff_s:
                    realized_pnl += (price - lot_cost_unit) * take
                lot_qty -= take
                remain -= take
                if lot_qty <= 1e-12:
                    pool.pop(0)
                else:
                    pool[0][0] = lot_qty

        else:
            continue

    cashflow_pnl = sell_vol - buy_vol - fees_in_window
    return dict(
        total_trades=total_trades_in_window,
        buy_volume_usdt=round(buy_vol, 2),
        sell_volume_usdt=round(sell_vol, 2),
        fees_usdt=round(fees_in_window, 2),
        cashflow_pnl_usdt=round(cashflow_pnl, 2),
        realized_pnl_usdt=round(realized_pnl, 2),
    )

def _api_creds() -> Tuple[str, str]:
    """Read dedicated read-only credentials on demand; do not retain globals."""
    return (
        os.getenv("DASHBOARD_BINANCE_API_KEY", "").strip(),
        os.getenv("DASHBOARD_BINANCE_API_SECRET", "").strip(),
    )


def ensure_api_creds() -> bool:
    key, secret = _api_creds()
    return bool(key and secret)

# ---- Binance helpers & equity-PNL ------------------------------------------------

def _pub_get(path: str, params=None, timeout: float = 10.0):
    r = SESSION.get(BINANCE_BASE + path, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _ts_ms() -> int:
    return int(time.time() * 1000)

def _sign(qs: str, secret: str) -> str:
    return hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()

def _signed(method: str, path: str, params=None, timeout: float = 10.0):
    if method.upper() not in ("GET", "HEAD"):
        raise RuntimeError("dashboard API credentials are read-only by design")
    key, secret = _api_creds()
    if not key or not secret:
        raise RuntimeError("No API creds")
    p = dict(params or {})
    p.setdefault("recvWindow", 5000)
    p["timestamp"] = _ts_ms()
    qs = requests.models.RequestEncodingMixin._encode_params(p)
    sig = _sign(qs, secret)
    url = f"{BINANCE_BASE}{path}?{qs}&signature={sig}"
    headers = {"X-MBX-APIKEY": key}
    r = SESSION.request(method, url, headers=headers, timeout=timeout)
    if r.status_code in (401, 403):
        try:
            error_payload = r.json()
        except ValueError:
            error_payload = {}
        notify_binance_auth_error(
            status=r.status_code,
            code=error_payload.get("code") if isinstance(error_payload, dict) else None,
            endpoint=path,
            message=error_payload.get("msg", "") if isinstance(error_payload, dict) else "",
        )
    r.raise_for_status()
    return r.json()

def price_now(symbol: str) -> float:
    j = _pub_get("/api/v3/ticker/price", {"symbol": symbol})
    return float(j["price"])

def price_at(symbol: str, ts_ms: int) -> float:
    j = _pub_get("/api/v3/klines", {"symbol": symbol, "interval": "1m", "startTime": ts_ms, "limit": 1})
    if not j:
        return price_now(symbol)
    return float(j[0][1])  # open

def account_balances_now() -> Dict[str, float]:
    """
    Возвращает dict asset-> qty (free+locked). Требует API ключи.
    """
    if not ensure_api_creds():
        raise RuntimeError("No API creds")
    j = _signed("GET", "/api/v3/account")
    out: Dict[str, float] = {}
    for b in j.get("balances", []):
        qty = float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
        if qty > 0:
            out[b["asset"].upper()] = qty
    return out


def account_balances_snapshot() -> Dict:
    """Снимок free/locked балансов и их USDT-оценки для read-only dashboard."""
    now = time.monotonic()
    with _BALANCE_CACHE_LOCK:
        cached = _BALANCE_CACHE.get("payload")
        if cached is not None and now - float(_BALANCE_CACHE.get("ts", 0.0)) < _BALANCE_CACHE_TTL_SEC:
            return cached  # type: ignore[return-value]

    if not ensure_api_creds():
        raise RuntimeError("No API creds")

    raw = _signed("GET", "/api/v3/account")
    try:
        ticker_rows = _pub_get("/api/v3/ticker/price")
        ticker_map = {
            str(row.get("symbol", "")).upper(): float(row.get("price", 0.0))
            for row in (ticker_rows if isinstance(ticker_rows, list) else [])
            if isinstance(row, dict) and row.get("symbol")
        }
    except (TypeError, ValueError, requests.RequestException):
        ticker_map = {}

    assets = []
    total_value = 0.0
    unvalued = []
    for balance in raw.get("balances", []):
        asset = str(balance.get("asset", "")).upper()
        free = float(balance.get("free", 0.0) or 0.0)
        locked = float(balance.get("locked", 0.0) or 0.0)
        total = free + locked
        if not asset or total <= 0:
            continue
        price = 1.0 if asset == "USDT" else ticker_map.get(asset + "USDT")
        value = total * price if price is not None and price > 0 else None
        if value is None:
            unvalued.append(asset)
        else:
            total_value += value
        assets.append({
            "asset": asset,
            "free": round(free, 8),
            "locked": round(locked, 8),
            "total": round(total, 8),
            "price_usdt": round(price, 8) if price is not None and price > 0 else None,
            "value_usdt": round(value, 2) if value is not None else None,
            "valuation_status": "priced" if value is not None else "unvalued",
        })

    assets.sort(key=lambda row: (row["asset"] != "USDT", -(row["value_usdt"] or 0.0), row["asset"]))
    payload = {
        "ok": True,
        "updated_at": now_str(),
        "venue": BINANCE_BASE,
        "assets": assets,
        "total_value_usdt": round(total_value, 2),
        "unvalued_assets": sorted(unvalued),
    }
    with _BALANCE_CACHE_LOCK:
        _BALANCE_CACHE["ts"] = now
        _BALANCE_CACHE["payload"] = payload
    return payload


def account_open_orders_snapshot() -> Dict:
    """Read-only снимок всех открытых Binance-ордеров с безопасными полями."""
    now = time.monotonic()
    with _OPEN_ORDERS_CACHE_LOCK:
        cached = _OPEN_ORDERS_CACHE.get("payload")
        if cached is not None and now - float(_OPEN_ORDERS_CACHE.get("ts", 0.0)) < _OPEN_ORDERS_CACHE_TTL_SEC:
            return cached  # type: ignore[return-value]

    if not ensure_api_creds():
        raise RuntimeError("No API creds")

    raw = _signed("GET", "/api/v3/openOrders")
    if not isinstance(raw, list):
        raise RuntimeError("Binance open orders response is not a list")

    orders = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        if not symbol:
            continue
        orig_qty = float(row.get("origQty", 0.0) or 0.0)
        executed_qty = float(row.get("executedQty", 0.0) or 0.0)
        orders.append({
            "order_id": row.get("orderId"),
            "client_order_id": str(row.get("clientOrderId", "")),
            "symbol": symbol,
            "side": str(row.get("side", "")).upper(),
            "type": str(row.get("type", "")).upper(),
            "time_in_force": str(row.get("timeInForce", "")),
            "price": float(row.get("price", 0.0) or 0.0),
            "stop_price": float(row.get("stopPrice", 0.0) or 0.0),
            "orig_qty": orig_qty,
            "executed_qty": executed_qty,
            "remaining_qty": max(0.0, orig_qty - executed_qty),
            "status": str(row.get("status", "OPEN")).upper(),
            "created_at": _ts_to_s(row.get("time", 0)),
            "updated_at": _ts_to_s(row.get("updateTime", row.get("time", 0))),
            "order_list_id": row.get("orderListId"),
        })

    orders.sort(key=lambda item: (item["symbol"], item["created_at"], str(item["order_id"])))
    payload = {
        "ok": True,
        "updated_at": now_str(),
        "venue": BINANCE_BASE,
        "count": len(orders),
        "orders": orders,
    }
    with _OPEN_ORDERS_CACHE_LOCK:
        _OPEN_ORDERS_CACHE["ts"] = now
        _OPEN_ORDERS_CACHE["payload"] = payload
    return payload


def _average_entry_from_ledger(symbol: str) -> Optional[float]:
    """Рассчитать FIFO average entry только по фактическим ledger fills."""
    try:
        con, _ = _open_db()
        rows = _load_trades(con, [symbol])
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    try:
        lots: List[List[float]] = []
        fee_pct = _fee_pct_default()
        for row in rows:
            price = float(row["price"])
            qty = float(row["qty"])
            fee = _estimate_fee_quote(price, qty, float(row["fee_quote"]), fee_pct)
            if str(row["side"]).upper() == "BUY":
                lots.append([qty, (price * qty + fee) / max(qty, 1e-12)])
            elif str(row["side"]).upper() == "SELL":
                remain = qty
                while remain > 1e-12 and lots:
                    take = min(remain, lots[0][0])
                    lots[0][0] -= take
                    remain -= take
                    if lots[0][0] <= 1e-12:
                        lots.pop(0)
        quantity = sum(item[0] for item in lots)
        if quantity <= 1e-12:
            return None
        return sum(item[0] * item[1] for item in lots) / quantity
    finally:
        con.close()


def _order_journal_snapshot(runtime: Dict[str, object]) -> Dict[str, object]:
    """Сводка intent-журнала без client secrets и без raw metadata."""
    paths = runtime.get("paths", {}) if isinstance(runtime.get("paths"), dict) else {}
    path = Path(str(paths.get("order_journal") or os.getenv(
        "BOT_ORDER_JOURNAL", "/home/bot/apps/binance_bot/db/order_intents.sqlite3"
    )))
    if not path.exists():
        return {"available": False, "reason": "order journal not found"}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1) as con:
            con.row_factory = sqlite3.Row
            columns = {str(row[1]) for row in con.execute("PRAGMA table_info(order_intents)")}
            if not {"state", "updated_at"}.issubset(columns):
                return {"available": False, "reason": "order journal schema unavailable"}
            counts = {
                str(row["state"]): int(row["count"])
                for row in con.execute("SELECT state, COUNT(*) AS count FROM order_intents GROUP BY state")
            }
            latest = con.execute(
                "SELECT symbol, side, state, exchange_order_id, executed_qty, quantity, updated_at "
                "FROM order_intents ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            item = None
            if latest:
                item = {
                    "symbol": latest["symbol"], "side": latest["side"], "status": latest["state"],
                    "order_id": latest["exchange_order_id"], "executed_qty": latest["executed_qty"],
                    "quantity": latest["quantity"], "partial_fill": (
                        str(latest["executed_qty"] or "0") not in {"0", "0.0"}
                        and str(latest["executed_qty"]) != str(latest["quantity"])
                    ),
                    # Intent-журнал пока не хранит сетевую latency и комиссию
                    # конкретного fill; явно возвращаем null, а не выдумываем их.
                    "latency_ms": None,
                    "commission_usdt": None,
                    "updated_at": datetime.fromtimestamp(float(latest["updated_at"]), APP_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                }
            cancelled = sum(value for key, value in counts.items() if "CANCEL" in key.upper())
            pending = sum(value for key, value in counts.items() if key.upper() not in {"FILLED", "CLOSED", "PROTECTED"} and "CANCEL" not in key.upper())
            return {"available": True, "counts": counts, "cancelled": cancelled, "pending": pending, "latest": item}
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        return {"available": False, "reason": type(exc).__name__}


def trading_overview_snapshot() -> Dict[str, object]:
    """Read-only объединённый снимок позиций, защиты и risk telemetry."""
    runtime = _load_ai_runtime_status()
    balances = account_balances_snapshot()
    orders = account_open_orders_snapshot()
    balance_by_asset = {str(row["asset"]).upper(): row for row in balances.get("assets", [])}
    runtime_symbols = runtime.get("symbols", []) if isinstance(runtime.get("symbols"), list) else []
    symbols = [str(item).upper() for item in runtime_symbols if item]
    if not symbols:
        symbols = [f"{asset}USDT" for asset in balance_by_asset if asset not in {"USDT", "BNB"}]
    order_rows = orders.get("orders", []) if isinstance(orders.get("orders"), list) else []
    positions = []
    for symbol in symbols:
        base = base_asset_of(symbol)
        balance = balance_by_asset.get(base, {})
        quantity = float(balance.get("total", 0.0) or 0.0)
        current = balance.get("price_usdt")
        if current is None:
            try:
                current = price_now(symbol)
            except Exception:
                current = None
        average = _average_entry_from_ledger(symbol)
        value = quantity * float(current) if current is not None else None
        unrealized = (float(current) - average) * quantity if current is not None and average is not None else None
        legs = [row for row in order_rows if row.get("symbol") == symbol and row.get("side") == "SELL"]
        leg_types = {str(row.get("type", "")).upper() for row in legs}
        if quantity <= 1e-12:
            protection_state = "not_needed"
        elif {"LIMIT_MAKER", "STOP_LOSS_LIMIT"}.issubset(leg_types):
            protection_state = "confirmed"
        elif legs:
            protection_state = "pending"
        else:
            protection_state = "not_checked"
        positions.append({
            "symbol": symbol, "quantity": round(quantity, 8), "average_entry_usdt": round(average, 8) if average is not None else None,
            "current_price_usdt": round(float(current), 8) if current is not None else None,
            "value_usdt": round(value, 2) if value is not None else None,
            "unrealized_pnl_usdt": round(unrealized, 2) if unrealized is not None else None,
            "drawdown_pct": round((float(current) / average - 1) * 100, 2) if current is not None and average else None,
            "protection": {
                "state": protection_state,
                "tp": [row.get("price") for row in legs if row.get("type") == "LIMIT_MAKER"],
                "stop": [row.get("stop_price") for row in legs if row.get("type") == "STOP_LOSS_LIMIT"],
                "locked_quantity": round(sum(float(row.get("remaining_qty", 0.0) or 0.0) for row in legs), 8),
                "gap_watchdog": "armed" if protection_state == "confirmed" else "warning",
            },
        })
    risk = runtime.get("risk", {}) if isinstance(runtime.get("risk"), dict) else {}
    risk_limits = runtime.get("risk_limits", {}) if isinstance(runtime.get("risk_limits"), dict) else {}
    risk_state_path = Path(os.getenv("CB_STATE_FILE", "/run/mybot/risk_state.json"))
    risk_state: Dict[str, object] = {}
    try:
        risk_state = json.loads(risk_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass
    free_usdt = float(balance_by_asset.get("USDT", {}).get("free", 0.0) or 0.0)
    journal = _order_journal_snapshot(runtime)
    reconciliation_delta = risk.get("reconciliation_delta")
    if reconciliation_delta is None:
        parsed = []
        for reason in risk.get("reasons", []) if isinstance(risk.get("reasons"), list) else []:
            match = re.search(r"(?P<symbol>[A-Z0-9]+): account=(?P<account>[0-9.]+), ledger=(?P<ledger>[0-9.]+)", str(reason))
            if match:
                account_qty = float(match.group("account")); ledger_qty = float(match.group("ledger"))
                parsed.append({"symbol": match.group("symbol"), "account": account_qty, "ledger": ledger_qty, "delta": round(account_qty - ledger_qty, 8)})
        reconciliation_delta = parsed or None
    return {
        "ok": True,
        "updated_at": now_str(),
        "venue": runtime.get("venue") or BINANCE_BASE,
        "execution_mode": runtime.get("execution_mode") or "UNKNOWN",
        "symbols": symbols,
        "free_usdt": round(free_usdt, 2),
        "reserve_usdt": risk_limits.get("reserve_usdt"),
        "caps": {
            "per_order_usdt": risk.get("current_cap_per_order_usdt"),
            "per_symbol": risk.get("symbol_caps_usdt", {}),
            "portfolio_usdt": risk_limits.get("portfolio_cap_usdt"),
        },
        "positions": positions,
        "orders": {"open": orders.get("count", 0), "cancelled": journal.get("cancelled"), "pending": journal.get("pending")},
        "last_order": journal.get("latest"),
        "risk": {
            "buy_blocked": bool(risk.get("buy_blocked", False)), "halted": bool(risk.get("halted", False)),
            "reasons": risk.get("reasons", []), "cooldown_until": risk_state.get("cooldown_until"),
            "reconciliation_delta": reconciliation_delta, "snapshot": risk.get("snapshot", {}),
        },
    }


@app.get("/api/trading/overview")
def trading_overview():
    try:
        return JSONResponse(trading_overview_snapshot())
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"trading overview failed: {type(exc).__name__}"}, status_code=503)

def base_asset_of(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith("USDT"): return s[:-4]
    if s.endswith("FDUSD"): return s[:-5]
    if s.endswith("TUSD"):  return s[:-4]
    return s[:-4]

# ---- Approx equity from DB (no API keys) ----------------------------------------

def _approx_equity_now_from_db(rows: List[sqlite3.Row], symbols_list: Optional[List[str]], fee_pct: float) -> Dict:
    """
    Приближённая оценка текущего equity (USDT) по указанным symbols.
    Так как в БД может не быть начальных депозитов/входов, любые ОТРИЦАТЕЛЬНЫЕ остатки
    (USDT, BNB и любые базовые активы) считаем нулём — это «неучтённая история».
    Комиссии, оплаченные BNB, учитываем как уменьшение BNB (но не ниже 0).
    """
    sym_set = set([s.strip().upper() for s in (symbols_list or []) if s.strip()])
    pos: Dict[str, float] = {"USDT": 0.0, "BNB": 0.0}
    fee_bnb_usdt_total = 0.0

    for r in rows:
        sym = (r["symbol"] or "").upper()
        if sym_set and sym not in sym_set:
            continue
        side = str(r["side"]).upper()
        qty  = float(r["qty"])
        px   = float(r["price"])
        fee_q = float(r["fee_quote"])  # 0 => оплачивалось BNB
        a = base_asset_of(sym)

        if side == "BUY":
            pos[a] = pos.get(a, 0.0) + qty
            pos["USDT"] -= px * qty
            if fee_q > 0:
                pos["USDT"] -= fee_q
            else:
                fee_bnb_usdt_total += (px * qty * _fee_pct_default())
        elif side == "SELL":
            pos[a] = pos.get(a, 0.0) - qty
            pos["USDT"] += px * qty
            if fee_q > 0:
                pos["USDT"] -= fee_q
            else:
                fee_bnb_usdt_total += (px * qty * _fee_pct_default())

    # цены сейчас для всех активов, что фигурируют
    assets = {k for k,v in pos.items() if abs(v) > 0} | {"BNB"}
    prices: Dict[str, float] = {"USDT": 1.0}
    for a in list(assets):
        if a == "USDT":
            continue
        try:
            prices[a] = price_now(f"{a}USDT")
        except Exception:
            prices[a] = 0.0

    # учёт комиссий в BNB (не ниже 0)
    p_bnb = prices.get("BNB", 0.0)
    if p_bnb > 0 and fee_bnb_usdt_total > 0:
        pos["BNB"] = max(0.0, pos.get("BNB", 0.0) - (fee_bnb_usdt_total / p_bnb))

    # Обрезаем отрицательные остатки ПО ВСЕМ активам (включая USDT/BNB)
    for a in list(pos.keys()):
        if pos[a] < 0:
            pos[a] = 0.0

    # equity_now >= 0
    eq_now = 0.0
    for a, q in pos.items():
        eq_now += q * (prices.get(a, 0.0))

    return {
        "equity_now_usdt": round(eq_now, 2),
        "pos": {k: round(v, 8) for k,v in pos.items() if v > 1e-12},
        "assets": sorted(list({k for k,v in pos.items() if v>1e-12} | {"USDT"})),
        "method": "db-holdings-minima",
    }

def equity_pnl_usdt(cutoff_s: int, rows: List[sqlite3.Row], fee_pct: float, symbols_list: Optional[List[str]]) -> Dict:
    """
    Возвращает словарь:
      - method: 'balances+klines' или 'approx'
      - equity_now_usdt, equity_then_usdt, equity_pnl_usdt
      - buy/sell/fees для совместимости
    Можно ограничить активы параметром symbols_list (по базовым активам соответствующих пар).
    """
    # Дельты и объёмы в окне, ограниченные symbols (если есть)
    buy_usdt = 0.0
    sell_usdt = 0.0
    dQ: Dict[str, float] = {}
    sym_set = set([s.strip().upper() for s in (symbols_list or []) if s.strip()])

    for r in rows:
        sym = (r["symbol"] or "").upper()
        if sym_set and sym not in sym_set:
            continue
        side = str(r["side"]).upper()
        qty  = float(r["qty"])
        px   = float(r["price"])
        ts_s = _ts_to_s(r["ts_s"])
        if ts_s < cutoff_s:
            continue
        if side == "BUY":
            buy_usdt += px * qty
            a = base_asset_of(sym)
            dQ[a] = dQ.get(a, 0.0) + qty
        elif side == "SELL":
            sell_usdt += px * qty
            a = base_asset_of(sym)
            dQ[a] = dQ.get(a, 0.0) - qty

    fees_usdt = (buy_usdt + sell_usdt) * fee_pct
    delta_usdt = sell_usdt - buy_usdt
    cutoff_ms = cutoff_s * 1000

    # точный метод с ключами
    try:
        bals_now = account_balances_now()  # требует API ключи (ensure_api_creds внутри)
        if sym_set:
            allowed_bases = {base_asset_of(s) for s in sym_set}
            assets = set(["USDT", "BNB"]) | allowed_bases
        else:
            assets = set(bals_now.keys()) | set(["USDT", "BNB"])

        # цены сейчас
        p_now: Dict[str, float] = {"USDT": 1.0}
        for a in list(assets):
            if a == "USDT": continue
            sym = f"{a}USDT"
            try: p_now[a] = price_now(sym)
            except Exception: p_now[a] = 0.0

        # цены тогда
        p_then: Dict[str, float] = {"USDT": 1.0}
        for a in list(assets):
            if a == "USDT": continue
            sym = f"{a}USDT"
            try: p_then[a] = price_at(sym, cutoff_ms)
            except Exception: p_then[a] = p_now.get(a, 0.0)

        # балансы «сейчас» ограничиваем
        q1 = {a: bals_now.get(a, 0.0) for a in assets}

        # восстанавливаем «тогда»
        q0 = dict(q1)
        q0["USDT"] = q1.get("USDT", 0.0) - delta_usdt
        for a, dq in dQ.items():
            if a in assets:
                q0[a] = q1.get(a, 0.0) - dq

        p_bnb_ref = (p_then.get("BNB") or p_now.get("BNB") or 0.0)
        if "BNB" in assets and p_bnb_ref > 0:
            q0["BNB"] = q1.get("BNB", 0.0) + (fees_usdt / p_bnb_ref)

        def equity(qmap: Dict[str, float], pmap: Dict[str, float]) -> float:
            s = 0.0
            for a, q in qmap.items():
                s += q * (pmap.get(a, 0.0))
            return s

        E_now  = equity(q1, p_now)
        E_then = equity(q0, p_then)

        return {
            "method": "balances+klines",
            "equity_now_usdt": round(E_now, 2),
            "equity_then_usdt": round(E_then, 2),
            "equity_pnl_usdt": round(E_now - E_then, 2),
            "buy_volume_usdt": round(buy_usdt, 2),
            "sell_volume_usdt": round(sell_usdt, 2),
            "fees_usdt": round(fees_usdt, 2),
            "equity_assets": sorted(list(set(assets))),
        }
    except Exception:
        # аппроксимация
        approx_now = _approx_equity_now_from_db(rows, symbols_list, fee_pct)
        p_now_local: Dict[str, float] = {}
        for a in dQ.keys():
            try:
                p_now_local[a] = price_now(f"{a}USDT")
            except Exception:
                p_now_local[a] = 0.0
        inv_delta = sum((p_now_local.get(a, 0.0) * dq) for a, dq in dQ.items())
        approx_pnl = delta_usdt + inv_delta - fees_usdt

        eq_now  = approx_now.get("equity_now_usdt")
        eq_then = (round(eq_now - approx_pnl, 2) if (eq_now is not None) else None)

        equity_pct = None
        # чтобы не было «-218%» при крошечном eq_then
        if (eq_then not in (None, 0)) and (equity_pct is None) and (eq_now is not None) and abs(eq_then) >= 10.0:
            try:
                equity_pct = round((eq_now - eq_then) / eq_then * 100.0, 2)
            except Exception:
                equity_pct = None

        return {
            "method": "db-holdings-minima",
            "equity_now_usdt": eq_now,
            "equity_then_usdt": eq_then,
            "equity_pnl_usdt": round(approx_pnl, 2),
            "equity_pct": equity_pct,
            "buy_volume_usdt": round(buy_usdt, 2),
            "sell_volume_usdt": round(sell_usdt, 2),
            "fees_usdt": round(fees_usdt, 2),
            "equity_assets": approx_now.get("assets"),
            "equity_now_usdt_approx": eq_now,
        }

# ------------------- system helpers (original) ------------------------------------

def run_command(*args: str, timeout=5):
    """Запустить только явно заданную команду без shell-интерпретации."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)

def now_local():
    return datetime.now(APP_TZ)

def now_str():
    return now_local().strftime("%Y-%m-%d %H:%M:%S")

def read_temp_c():
    rc,out = run_command("vcgencmd", "measure_temp")
    if rc==0 and "temp=" in out:
        try:
            return float(out.split("=",1)[1].split("'")[0])
        except Exception:
            pass
    for p in ("/sys/class/thermal/thermal_zone0/temp","/sys/devices/virtual/thermal/thermal_zone0/temp"):
        try:
            with open(p) as f:
                v = f.read().strip()
                val = float(v)/1000.0 if float(v)>200 else float(v)
                return round(val,1)
        except Exception:
            continue
    return None

def parse_throttled():
    rc,out = run_command("vcgencmd", "get_throttled")
    raw = out.strip() or "throttled=0x0"
    try:
        hexstr = raw.split("0x",1)[1]
        val = int(hexstr,16)
    except Exception:
        val = 0
    def b(n): return bool((val>>n)&1)
    return {
        "raw": raw,
        "under_voltage_now": b(0),
        "freq_capped_now": b(1),
        "throttled_now": b(2),
        "temp_limit_now": b(3),
        "under_voltage_hist": b(16),
        "freq_capped_hist": b(17),
        "throttled_hist": b(18),
        "temp_limit_hist": b(19),
    }

def network_ok():
    try:
        with socket.create_connection(("1.1.1.1",53), 0.5): pass
        return True
    except Exception:
        return False

def mounts_info():
    res = []
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    dev, mnt, fstype, opts = parts[:4]
                    if mnt in ("/","/tmp","/var/tmp","/mnt/usb1"):
                        res.append({"mountpoint": mnt, "fs": fstype, "opts": opts})
    except Exception:
        pass
    return res

def service_active(name: str):
    if name not in {"mybot", "pi-healthd"}:
        return "invalid"
    rc,out = run_command("systemctl", "is-active", name, timeout=2)
    return out.strip()

def fail2ban_bans(jail="sshd"):
    if jail != "sshd":
        return 0
    rc,out = run_command("fail2ban-client", "status", jail)
    count = 0
    try:
        for line in out.splitlines():
            if "Currently banned" in line:
                count = int(line.strip().split()[-1])
                break
    except Exception:
        pass
    return count


def _command_value(*args: str) -> str:
    """Безопасно прочитать одну строку системной telemetry-команды."""
    _rc, output = run_command(*args, timeout=3)
    return output.strip().splitlines()[0].strip() if output.strip() else ""


def _systemd_service_snapshot(name: str) -> Dict[str, object]:
    """Статус и время запуска сервиса без чтения секретов или /proc."""
    if name not in {"mybot", "pi-healthd"}:
        return {"state": "invalid"}
    _rc, output = run_command(
        "systemctl", "show", name,
        "-p", "ActiveState", "-p", "SubState", "-p", "ActiveEnterTimestamp",
        "-p", "ActiveEnterTimestampMonotonic", "-p", "NRestarts",
        timeout=3,
    )
    values: Dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip()
    boot = psutil.boot_time()
    started_at = None
    age_sec = None
    try:
        monotonic_usec = int(values.get("ActiveEnterTimestampMonotonic", "0"))
        if monotonic_usec > 0:
            started_epoch = boot + monotonic_usec / 1_000_000
            started_at = datetime.fromtimestamp(started_epoch, timezone.utc).astimezone(APP_TZ).strftime("%Y-%m-%d %H:%M:%S")
            age_sec = max(0, int(time.time() - started_epoch))
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    try:
        restarts = int(values.get("NRestarts", "0"))
    except ValueError:
        restarts = 0
    return {
        "state": values.get("ActiveState", "unknown"),
        "substate": values.get("SubState", "unknown"),
        "started_at": started_at,
        "age_sec": age_sec,
        "restart_count": restarts,
    }


def _ntp_snapshot() -> Dict[str, object]:
    """Состояние синхронизации часов, доступное без прав администратора."""
    synced = _command_value("timedatectl", "show", "-p", "NTPSynchronized", "--value").lower()
    service = _command_value("timedatectl", "show", "-p", "NTPService", "--value")
    return {
        "synchronized": synced in {"yes", "true", "1"},
        "service": service or None,
    }


def _binance_latency_snapshot() -> Dict[str, object]:
    """Проверить public Binance clock с коротким кэшем, не используя торговые права."""
    started = time.monotonic()
    try:
        payload = _pub_get("/api/v3/time", timeout=5.0)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        server_ms = payload.get("serverTime") if isinstance(payload, dict) else None
        offset_ms = round(float(server_ms) - time.time() * 1000, 1) if server_ms is not None else None
        return {"ok": True, "latency_ms": elapsed_ms, "offset_ms": offset_ms, "checked_at": now_str(), "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": None, "offset_ms": None, "checked_at": now_str(), "error": type(exc).__name__}


def _backup_snapshot() -> Dict[str, object]:
    """Показать только метаданные последнего age-архива, без содержимого."""
    public_dir = Path(os.getenv("DASHBOARD_BACKUP_PUBLIC_DIR", "/var/lib/ladder-dragon/backups-public"))
    status_payload: Dict[str, object] = {}
    for status_path in (
        Path(os.getenv("DASHBOARD_BACKUP_STATUS_FILE", "/run/mybot/backup_status.json")),
        public_dir / "backup_status.json",
    ):
        try:
            raw_status = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(raw_status, dict):
                status_payload = raw_status
                break
        except (OSError, ValueError, TypeError):
            continue
    archives = []
    try:
        archives = sorted(public_dir.glob("ladder-dragon-*.tgz.age"), key=lambda p: p.stat().st_mtime)
    except (OSError, PermissionError):
        return {"status": status_payload.get("status", "unavailable"), "reason": status_payload.get("reason", "backup directory is not readable"), "directory": str(public_dir)}
    if not archives:
        return {"status": status_payload.get("status", "unknown"), "reason": status_payload.get("reason", "no encrypted archive found"), "directory": str(public_dir)}
    latest = archives[-1]
    try:
        stat = latest.stat()
        return {
            "status": status_payload.get("status", "success"),
            "reason": status_payload.get("reason"),
            "directory": str(public_dir),
            "last_success": {
                "name": latest.name,
                "size_bytes": stat.st_size,
                "age_sec": max(0, int(time.time() - stat.st_mtime)),
                "updated_at": datetime.fromtimestamp(stat.st_mtime, APP_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            },
            "archive_count": len(archives),
        }
    except OSError as exc:
        return {"status": "unavailable", "reason": type(exc).__name__, "directory": str(public_dir)}


def _usb_snapshot() -> Dict[str, object]:
    """Состояние внешнего диска и свободное место для backup mirror."""
    mountpoint = os.getenv("DASHBOARD_BACKUP_MOUNT", "/mnt/usb1")
    mounted = _command_value("findmnt", "-T", mountpoint, "-no", "TARGET") == mountpoint
    options = _command_value("findmnt", "-T", mountpoint, "-no", "OPTIONS") if mounted else ""
    writable = mounted and "ro" not in {item.strip() for item in options.split(",")}
    payload: Dict[str, object] = {"mountpoint": mountpoint, "mounted": mounted, "writable": writable, "options": options, "free_gib": None, "used_percent": None}
    if mounted:
        try:
            usage = shutil.disk_usage(mountpoint)
            payload.update({"free_gib": round(usage.free / GiB, 3), "used_percent": round(usage.used * 100 / usage.total, 1)})
        except OSError as exc:
            payload["error"] = type(exc).__name__
    return payload

async def collect_once():
    vm = psutil.virtual_memory()
    temp = read_temp_c()
    cpu = psutil.cpu_percent(interval=None)
    row = {
        "ts": int(time.time()),
        "temp_c": round(temp if temp is not None else 0.0, 1),
        "mem_total_gib": round(vm.total/GiB, 3),
        "mem_used_gib": round(vm.used/GiB, 3),
        "cpu_pct": round(cpu, 1),
    }
    try:
        max_bytes = max(1024, int(os.getenv("DASHBOARD_METRICS_MAX_BYTES", "5242880")))
        keep = max(1, int(os.getenv("DASHBOARD_METRICS_ROTATIONS", "3")))
        if HIST_FILE.exists() and HIST_FILE.stat().st_size >= max_bytes:
            oldest = HIST_FILE.with_suffix(HIST_FILE.suffix + f".{keep}")
            try:
                oldest.unlink()
            except FileNotFoundError:
                pass
            for idx in range(keep - 1, 0, -1):
                source = HIST_FILE.with_suffix(HIST_FILE.suffix + f".{idx}")
                if source.exists():
                    source.replace(HIST_FILE.with_suffix(HIST_FILE.suffix + f".{idx + 1}"))
            HIST_FILE.replace(HIST_FILE.with_suffix(HIST_FILE.suffix + ".1"))
        with open(HIST_FILE, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass

async def collector_loop():
    await collect_once()
    while True:
        try:
            await collect_once()
        except Exception:
            pass
        await asyncio.sleep(60)

@app.get("/api/health")
def health():
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    temp = read_temp_c()
    disk = shutil.disk_usage("/")
    now_mono = time.monotonic()
    with _OPS_CACHE_LOCK:
        ops = _OPS_CACHE.get("payload")
        if ops is None or now_mono - float(_OPS_CACHE.get("ts", 0.0)) >= _OPS_CACHE_TTL_SEC:
            load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
            ops = {
                "load_avg": {"1m": load[0], "5m": load[1], "15m": load[2]},
                "services": {
                    "mybot": _systemd_service_snapshot("mybot"),
                    "pi_healthd": _systemd_service_snapshot("pi-healthd"),
                },
                "ntp": _ntp_snapshot(),
                "binance": _binance_latency_snapshot(),
                "usb_backup": _usb_snapshot(),
                "backup": _backup_snapshot(),
            }
            _OPS_CACHE["ts"] = now_mono
            _OPS_CACHE["payload"] = ops
    network_probe_ok = network_ok()
    effective_network_ok = network_probe_ok or bool((ops.get("binance") or {}).get("ok"))
    return JSONResponse({
        "product": {"name": PRODUCT_NAME, "version": __version__},
        "changelog_url": "/CHANGELOG.md",
        "time": now_str(),
        "kernel": os.uname().release,
        "temp_c": temp,
        "throttled": parse_throttled(),
        "mem_gib": {
            "total": round(vm.total/GiB,3),
            "used": round(vm.used/GiB,3),
            "percent": vm.percent
        },
        "swap_gib": {
            "total": round(sm.total/GiB,3),
            "used": round(sm.used/GiB,3),
            "percent": sm.percent
        },
        "disk_gib": {
            "total": round(disk.total/GiB,3),
            "used": round(disk.used/GiB,3),
            "percent": round(disk.used*100.0/disk.total,1)
        },
        "mounts": mounts_info(),
        "services": {
            "mybot": service_active("mybot"),
            "fail2ban_sshd_bans": fail2ban_bans("sshd")
        },
        "uptime_sec": int(time.time() - psutil.boot_time()),
        # DNS/53 может быть закрыт в локальной сети; успешный Binance probe
        # является более релевантным признаком доступности торгового канала.
        "network_ok": effective_network_ok,
        "network_probe_ok": network_probe_ok,
        "operations": ops
    })


@app.get("/api/account/balances")
def account_balances():
    """Показать только балансы; торговые методы dashboard намеренно запрещены."""
    try:
        return JSONResponse(account_balances_snapshot())
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"account balance snapshot failed: {exc}"},
            status_code=503,
        )


@app.get("/api/account/open-orders")
def account_open_orders():
    """Показать все открытые ордера через выделенный read-only API-ключ."""
    try:
        return JSONResponse(account_open_orders_snapshot())
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"open orders snapshot failed: {exc}"},
            status_code=503,
        )

@app.get("/api/history")
def history(hours: int = 24, points: int = 288):
    hours = max(1, min(hours, 168))
    cutoff = int(time.time()) - hours*3600
    rows = []
    try:
        with open(HIST_FILE) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if obj.get("ts",0) >= cutoff:
                        rows.append(obj)
                except Exception:
                    continue
    except FileNotFoundError:
        rows = []

    if len(rows) > points and points > 0:
        step = max(1, len(rows)//points)
        rows = rows[::step]

    labels = [datetime.fromtimestamp(r["ts"], APP_TZ).strftime("%H:%M") for r in rows]
    return JSONResponse({
        "labels": labels,
        "temp_c": [r.get("temp_c") for r in rows],
        "mem_used_gib": [r.get("mem_used_gib") for r in rows],
        "cpu_pct": [r.get("cpu_pct") for r in rows],
    })


def _ai_usage_today(path: Path, *, now: datetime | None = None) -> Dict:
    # Лимиты и состояние DEGRADED должны совпадать с AI policy и сбрасываться
    # по UTC. APP_TZ используется только для отображения локального времени.
    now = now or datetime.now(tz=timezone.utc)
    now = now.astimezone(timezone.utc)
    today = now.date()
    requests_count = tokens = errors = recent_errors = 0
    cost = Decimal("0")
    last_error_at = None
    if not path.exists():
        return {
            "requests": 0,
            "tokens": 0,
            "cost_usd": "0",
            "errors": 0,
            "recent_errors": 0,
            "last_error_at": None,
            "error_window_sec": AI_ERROR_DEGRADED_WINDOW_SEC,
        }
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
            stamp = datetime.fromisoformat(str(event["timestamp"])).astimezone(timezone.utc)
            if stamp.date() != today:
                continue
            requests_count += 1
            tokens += int(event.get("total_tokens") or 0)
            cost += Decimal(str(event.get("estimated_cost_usd") or "0"))
            if event.get("outcome") == "error":
                errors += 1
                last_error_at = max(last_error_at or stamp, stamp).isoformat()
                age = (now - stamp).total_seconds()
                if 0 <= age <= AI_ERROR_DEGRADED_WINDOW_SEC:
                    recent_errors += 1
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return {
        "requests": requests_count,
        "tokens": tokens,
        "cost_usd": str(cost),
        "errors": errors,
        "recent_errors": recent_errors,
        "last_error_at": last_error_at,
        "error_window_sec": AI_ERROR_DEGRADED_WINDOW_SEC,
    }


def _ai_calibration(recent: List[Dict]) -> List[Dict]:
    result = []
    for low, high in ((0, .65), (.65, .70), (.70, .80), (.80, 1.01)):
        rows = [
            row for row in recent
            if low <= float(row.get("confidence") or 0) < high
            and row.get("return_1h") is not None
        ]
        success = 0
        for row in rows:
            ret = float(row["return_1h"])
            mode = row.get("recommended_mode")
            success += int(
                (mode == "UP" and ret > .001)
                or (mode == "DOWN" and ret < -.001)
                or (mode == "FLAT" and abs(ret) <= .001)
            )
        result.append({
            "bucket": f"{low:.2f}-{min(high, 1):.2f}",
            "samples": len(rows),
            "accuracy": success / len(rows) if rows else 0,
        })
    return result


@app.get("/api/ai/status")
def ai_status(limit: int = 50):
    """Защищённый read-only статус AI, решений и дневного расхода."""
    limit = max(1, min(int(limit), 200))
    runtime = _load_ai_runtime_status()
    runtime_ai = runtime.get("ai", {}) if isinstance(runtime.get("ai"), dict) else {}
    runtime_budgets = (
        runtime_ai.get("budgets", {})
        if isinstance(runtime_ai.get("budgets"), dict) else {}
    )
    runtime_age_sec = None
    try:
        runtime_age_sec = max(
            0,
            int(time.time() - datetime.fromisoformat(runtime["updated_at"]).timestamp()),
        )
    except (KeyError, TypeError, ValueError):
        pass
    runtime_stale = bool(
        runtime and (runtime_age_sec is None or runtime_age_sec > 90)
    )
    effective_mode = str(runtime_ai.get("mode") or AI_MODE).upper()
    recent = []
    knowledge_stats = {
        "documents": 0, "virtual_documents": 0, "retrievals": 0,
        "unresolved_fills": 0, "closed_decisions": 0,
        "realized_net_pnl_quote": 0.0,
    }
    db_path = _runtime_data_path(runtime, "ai_decisions_db", AI_DECISIONS_DB)
    if db_path.exists():
        try:
            with sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True, timeout=1
            ) as connection:
                connection.row_factory = sqlite3.Row
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(ai_decisions)")
                }
                expressions = {
                    "decision_id": "decision_id" if "decision_id" in columns else "''",
                    "policy_status": (
                        "policy_status" if "policy_status" in columns else "''"
                    ),
                    "policy_reasons": (
                        "policy_reasons" if "policy_reasons" in columns else "''"
                    ),
                    "benchmark_mode": (
                        "benchmark_mode" if "benchmark_mode" in columns else "''"
                    ),
                    "evaluation_json": (
                        "evaluation_json" if "evaluation_json" in columns else "'{}'"
                    ),
                    "rationale": "rationale" if "rationale" in columns else "''",
                    "context_version": "context_version" if "context_version" in columns else "''",
                    "config_version": "config_version" if "config_version" in columns else "''",
                }
                recent = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT {expressions['decision_id']} AS decision_id,symbol,created_at,deterministic_mode AS baseline_mode,
                               recommended_mode,width_scale,cap_scale,confidence,
                               applied,{expressions['policy_status']} AS status,
                               {expressions['policy_reasons']} AS policy_reasons,
                               {expressions['benchmark_mode']} AS benchmark_mode,
                               return_15m,return_1h,return_4h,
                               {expressions['evaluation_json']} AS evaluation_json,
                               {expressions['rationale']} AS rationale,
                               {expressions['context_version']} AS context_version,
                               {expressions['config_version']} AS config_version
                        FROM ai_decisions ORDER BY created_at DESC LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                ]
                for row in recent:
                    row["evaluation"] = json.loads(row.pop("evaluation_json") or "{}")
                closed_rows = connection.execute(
                    f"SELECT {expressions['evaluation_json']} AS evaluation_json FROM ai_decisions"
                ).fetchall()
                for closed_row in closed_rows:
                    try:
                        realized = json.loads(closed_row["evaluation_json"] or "{}").get("realized_execution", {})
                    except (TypeError, ValueError, json.JSONDecodeError):
                        realized = {}
                    if isinstance(realized, dict) and realized.get("closed"):
                        knowledge_stats["closed_decisions"] += 1
                        knowledge_stats["realized_net_pnl_quote"] += float(
                            realized.get("net_pnl_quote", 0) or 0
                        )
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "knowledge_documents" in tables:
                    knowledge_stats["documents"] = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM knowledge_documents "
                            "WHERE status='validated'"
                        ).fetchone()[0]
                    )
                    knowledge_stats["virtual_documents"] = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM knowledge_documents "
                            "WHERE status='virtual_validated'"
                        ).fetchone()[0]
                    )
                if "knowledge_retrievals" in tables:
                    knowledge_stats["retrievals"] = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM knowledge_retrievals"
                        ).fetchone()[0]
                    )
                    for row in recent:
                        decision_id = row.get("decision_id")
                        if not decision_id:
                            row["rag_documents"] = []
                            continue
                        row["rag_documents"] = [
                            {"document_id": item[0], "rank": int(item[1]), "score": float(item[2])}
                            for item in connection.execute(
                                """SELECT document_id,rank,score FROM knowledge_retrievals
                                   WHERE decision_id=? ORDER BY rank LIMIT 5""",
                                (decision_id,),
                            ).fetchall()
                        ]
                if "ai_unresolved_fills" in tables:
                    knowledge_stats["unresolved_fills"] = int(
                        connection.execute("SELECT COUNT(*) FROM ai_unresolved_fills").fetchone()[0]
                    )
        except sqlite3.Error as exc:
            return JSONResponse(
                {"ok": False, "error": f"AI DB read failed: {exc}"},
                status_code=500,
            )
    usage_path = _runtime_data_path(runtime, "ai_usage_log", AI_USAGE_LOG)
    usage = _ai_usage_today(usage_path)
    def _file_age(path: Path) -> Optional[int]:
        try:
            return max(0, int(time.time() - path.stat().st_mtime))
        except OSError:
            return None
    request_limit = int(
        runtime_budgets.get("max_requests_per_day", AI_MAX_REQUESTS_PER_DAY)
    )
    token_limit = int(
        runtime_budgets.get("max_tokens_per_day", AI_DAILY_TOKEN_LIMIT)
    )
    cost_limit = Decimal(
        str(runtime_budgets.get("max_cost_usd_per_day", AI_DAILY_COST_LIMIT_USD))
    )
    budget_exhausted = (
        (request_limit > 0 and usage["requests"] >= request_limit)
        or (token_limit > 0 and usage["tokens"] >= token_limit)
        or (cost_limit > 0 and Decimal(usage["cost_usd"]) >= cost_limit)
    )
    runtime_unhealthy = (
        (DASHBOARD_FOLLOW_BOT_PATHS and not runtime)
        or runtime_stale
        or bool(runtime and runtime.get("state") != "RUNNING")
    )
    degraded_reasons = []
    if budget_exhausted:
        degraded_reasons.append("daily_budget_exhausted")
    if usage.get("recent_errors", 0) >= AI_ERROR_DEGRADED_MIN:
        degraded_reasons.append("recent_ai_errors")
    if effective_mode == "APPLY":
        # В APPLY отклонение production-gate — самостоятельная причина
        # DEGRADED: модель может отвечать, но её статистика пока не допускает
        # влияние на стратегию.
        for row in recent:
            if str(row.get("status", "")).upper() != "REJECTED":
                continue
            for reason in str(row.get("policy_reasons", "")).split(","):
                reason = reason.strip()
                if reason and f"policy:{reason}" not in degraded_reasons:
                    degraded_reasons.append(f"policy:{reason}")
    if runtime_unhealthy:
        degraded_reasons.append("runtime_unhealthy")
    degraded = bool(degraded_reasons)
    state = (
        "DISABLED" if effective_mode == "DISABLED"
        else "DEGRADED" if degraded
        else "ACTIVE" if effective_mode == "APPLY"
        else "SHADOW"
    )
    edge_values = [
        int(
            (row.get("recommended_mode") == "UP" and row["return_1h"] > .001)
            or (row.get("recommended_mode") == "DOWN" and row["return_1h"] < -.001)
            or (row.get("recommended_mode") == "FLAT" and abs(row["return_1h"]) <= .001)
        ) - int(
            (row.get("baseline_mode") == "UP" and row["return_1h"] > .001)
            or (row.get("baseline_mode") == "DOWN" and row["return_1h"] < -.001)
            or (row.get("baseline_mode") == "FLAT" and abs(row["return_1h"]) <= .001)
        )
        for row in recent if row.get("return_1h") is not None
    ]
    return {
        "ok": True,
        "mode": effective_mode,
        "state": state,
        "runtime": {
            "connected": bool(runtime),
            "stale": runtime_stale,
            "age_sec": runtime_age_sec,
            "process_state": runtime.get("state"),
            "updated_at": runtime.get("updated_at"),
            "venue": runtime.get("venue"),
            "execution_mode": runtime.get("execution_mode"),
            "provider": runtime_ai.get("provider"),
            "model": runtime_ai.get("model"),
            "product": runtime.get("product"),
            "last_decision": runtime.get("last_decision"),
        },
        "data_sources": {
            "follow_bot_paths": DASHBOARD_FOLLOW_BOT_PATHS,
            "decisions_db": str(db_path),
            "usage_log": str(usage_path),
            "decision_db_age_sec": _file_age(db_path),
            "usage_log_age_sec": _file_age(usage_path),
            "context_age_sec": runtime_age_sec,
        },
        "knowledge_base": knowledge_stats,
        "usage_today": usage,
        "budget_exhausted": budget_exhausted,
        "degraded_reasons": degraded_reasons,
        "recent": recent,
        "applied_count": sum(bool(row.get("applied")) for row in recent),
        "changed_mode_count": sum(
            row.get("recommended_mode") != row.get("baseline_mode")
            for row in recent
        ),
        "calibration_1h": _ai_calibration(recent),
        "ai_vs_baseline_1h": {
            "samples": len(edge_values),
            "edge": sum(edge_values) / len(edge_values) if edge_values else 0,
        },
    }


def _ai_control_snapshot() -> Dict[str, object]:
    """Собрать состояние переключателя без доступа к ключам или ордерам."""
    runtime = _load_ai_runtime_status()
    runtime_ai = runtime.get("ai", {}) if isinstance(runtime.get("ai"), dict) else {}
    configured = bool(runtime_ai.get("enabled"))
    configured_mode = str(runtime_ai.get("configured_mode") or AI_MODE).upper()
    control_error = None
    try:
        control = read_ai_control(AI_CONTROL_FILE)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        control = None
        control_error = str(exc)
    if control is None:
        enabled = configured and configured_mode != "DISABLED"
        mode = configured_mode if enabled else "DISABLED"
    else:
        enabled = bool(control.get("enabled")) and configured
        mode = configured_mode if enabled else "DISABLED"
    return {
        "configured": configured,
        "enabled": enabled,
        "mode": mode,
        "configured_mode": configured_mode,
        "control_error": control_error,
        "updated_at": control.get("updated_at") if control else None,
    }


@app.get("/api/ai/control")
def ai_control():
    """Вернуть состояние runtime-переключателя AI."""
    snapshot = _ai_control_snapshot()
    if snapshot["control_error"]:
        return JSONResponse(
            {"ok": False, "error": "AI control file is invalid", **snapshot},
            status_code=503,
        )
    return {"ok": True, **snapshot}


@app.post("/api/ai/control")
async def set_ai_control(request: Request):
    """Включить/отключить только advisory AI; торговые права не меняются."""
    snapshot = _ai_control_snapshot()
    if not snapshot["configured"] or snapshot["configured_mode"] == "DISABLED":
        return JSONResponse(
            {"ok": False, "error": "AI advisor is not configured", **snapshot},
            status_code=409,
        )
    try:
        payload = await request.json()
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "JSON body is required"}, status_code=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
        return JSONResponse(
            {"ok": False, "error": "enabled must be boolean"}, status_code=400
        )
    try:
        document = write_ai_control(
            AI_CONTROL_FILE,
            enabled=payload["enabled"],
            mode=str(snapshot["configured_mode"]),
        )
    except (OSError, TypeError, ValueError) as exc:
        return JSONResponse(
            {"ok": False, "error": f"AI control write failed: {exc}"},
            status_code=503,
        )
    return {
        "ok": True,
        "configured": True,
        "enabled": bool(document["enabled"]),
        "mode": document["mode"],
        "updated_at": document["updated_at"],
    }

# ---- trades symbols ---------------------------------------------------------------

@app.get("/api/trades/symbols")
def trades_symbols(hours: int = 168):
    """
    Возвращает список уникальных symbol из таблицы trades.
    По умолчанию за последние 168 часов (7 дней). Если hours<=0 — по всей БД.
    """
    hours = int(hours)
    cutoff = int(time.time()) - max(0, hours) * 3600 if hours > 0 else 0
    try:
        con, _ = _open_db()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"db open failed: {e}"}, status_code=500)
    try:
        if hours > 0:
            sql = """
              SELECT DISTINCT symbol
              FROM trades
              WHERE (CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END) >= ?
              ORDER BY symbol
            """
            rows = con.execute(sql, (cutoff,)).fetchall()
        else:
            sql = "SELECT DISTINCT symbol FROM trades ORDER BY symbol"
            rows = con.execute(sql).fetchall()
        syms = [r["symbol"] for r in rows if r["symbol"]]
        return JSONResponse({"ok": True, "symbols": syms})
    finally:
        try: con.close()
        except Exception: pass

# ---- trades summary & recent ------------------------------------------------------

@app.get("/api/trades/summary")
def trades_summary(hours: int = 24, symbols: str = ""):
    """
    Агрегаты + три вида PnL:
      - cashflow_pnl_usdt: продажи − покупки − комиссии (денежный поток)
      - realized_pnl_usdt: FIFO по SELL в окне (с учётом комиссий)
      - equity_pnl_usdt / net_pnl_usdt: изменение капитала по выбранным активам
    Комиссии: fee_quote из БД или оценка BOT_FEE_PCT * notional (оплата BNB).
    Для equity используется Binance API (балансы + цены «тогда/сейчас»); при ошибке — приближение.
    Можно ограничить активы параметром symbols=BTCUSDT,ETHUSDT,...
    """
    hours = max(1, min(int(hours), 168))
    cutoff_s = int(time.time()) - hours * 3600
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None

    try:
        con, path = _open_db()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"db open failed: {e}", "path": get_db_path()}, status_code=500)

    fee_pct = _fee_pct_default()
    try:
        rows = _load_trades(con, syms)
        stats = _fifo_realized_pnl(rows, cutoff_s, fee_pct)
        eq = equity_pnl_usdt(cutoff_s, rows, fee_pct, syms)

        equity_then = eq.get("equity_then_usdt")
        equity_pnl  = eq.get("equity_pnl_usdt")
        equity_pct  = eq.get("equity_pct")
        if equity_pct is None and (equity_then not in (None, 0)) and (equity_pnl is not None) and abs(equity_then) >= 10.0:
            try:
                equity_pct = round((equity_pnl / equity_then) * 100.0, 2)
            except Exception:
                equity_pct = None

        return JSONResponse({
            "ok": True,
            "hours": hours,
            "symbols": "" if not syms else ",".join(syms),
            "total_trades": stats["total_trades"],
            "buy_volume_usdt": stats["buy_volume_usdt"],
            "sell_volume_usdt": stats["sell_volume_usdt"],
            "fees_usdt": stats["fees_usdt"],
            "cashflow_pnl_usdt": stats["cashflow_pnl_usdt"],
            "realized_pnl_usdt": stats["realized_pnl_usdt"],
            # equity / net
            "net_pnl_usdt": eq["equity_pnl_usdt"],
            "equity_pnl_usdt": eq["equity_pnl_usdt"],
            "equity_now_usdt": eq.get("equity_now_usdt"),
            "equity_now_usdt_approx": eq.get("equity_now_usdt_approx"),
            "equity_then_usdt": equity_then,
            "equity_pct": equity_pct,
            "equity_method": eq.get("method"),
            "equity_assets": eq.get("equity_assets"),
            "path": get_db_path()
        })
    finally:
        try: con.close()
        except Exception: pass

@app.get("/api/trades/recent")
def trades_recent(limit: int = 20, symbols: str = ""):
    limit = max(1, min(int(limit), 5000))
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    try:
        con, path = _open_db()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"db open failed: {e}", "path": get_db_path()}, status_code=500)
    try:
        sym_filter = ""
        args: List = []
        if syms:
            qs = ",".join("?" for _ in syms)
            sym_filter = f" AND symbol IN ({qs})"
            args.extend(syms)
        sql = f"""
        SELECT symbol, side, price, qty,
               COALESCE(fee_quote, 0.0) AS fee_quote,
               CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
        FROM trades
        WHERE 1=1 {sym_filter}
        ORDER BY ts_s DESC
        LIMIT ?
        """
        args.append(limit)
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
        for r in rows:
            r["time"] = datetime.fromtimestamp(int(r["ts_s"]), APP_TZ).strftime("%Y-%m-%d %H:%M:%S")
        return JSONResponse({"ok": True, "rows": rows, "path": get_db_path()})
    finally:
        try: con.close()
        except Exception: pass

# ---- Filled orders (24h) for dashboard -------------------------------------------

def _select_filled_orders(hours: int, syms: Optional[List[str]], limit: int) -> List[Dict]:
    """
    Возвращает список «исполненных ордеров» (по сути trades) за окно hours, newest-first.
    Формат полей совместим с фронтендом:
      time(ms), symbol, side, price, qty, quoteQty, commission, commissionAsset
    """
    hours = max(1, min(int(hours), 168))
    limit = max(1, min(int(limit), 5000))
    cutoff_s = int(time.time()) - hours * 3600

    con = None
    try:
        con, _ = _open_db()
    except Exception:
        return []

    try:
        sym_filter = ""
        args: List = []
        if syms:
            qs = ",".join("?" for _ in syms)
            sym_filter = f" AND symbol IN ({qs})"
            args.extend(syms)

        sql = f"""
        SELECT
          symbol, side, price, qty,
          COALESCE(fee_quote, 0.0) AS fee_quote,
          CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
        FROM trades
        WHERE 1=1 {sym_filter}
          AND (CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END) >= ?
        ORDER BY ts_s DESC
        LIMIT ?
        """
        args.extend([cutoff_s, limit])
        rows = con.execute(sql, args).fetchall()

        fee_pct = _fee_pct_default()
        out: List[Dict] = []
        for r in rows:
            price = float(r["price"])
            qty = float(r["qty"])
            fee_q = float(r["fee_quote"])
            # если fee_quote==0 (BNB), считаем комиссию в USDT по проценту
            fee_usdt = fee_q if fee_q > 0 else (price * qty * fee_pct)
            out.append({
                "time": int(r["ts_s"]) * 1000,
                "symbol": r["symbol"],
                "side": str(r["side"]).upper(),
                "price": round(price, 8),
                "qty": round(qty, 8),
                "quoteQty": round(price * qty, 8),
                "commission": round(fee_usdt, 8),
                "commissionAsset": "USDT"  # всегда в USDT для единообразия отображения
            })
        return out
    finally:
        try:
            if con: con.close()
        except Exception:
            pass

@app.get("/api/trades/filled")
def api_trades_filled(hours: int = 24, symbols: str = "", limit: int = 5000):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    items = _select_filled_orders(hours, syms, limit)
    return JSONResponse(items)

@app.get("/api/orders/filled")
def api_orders_filled(hours: int = 24, symbols: str = "", limit: int = 5000):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    items = _select_filled_orders(hours, syms, limit)
    return JSONResponse(items)

@app.get("/api/fills")
def api_fills(hours: int = 24, symbols: str = "", limit: int = 5000):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    items = _select_filled_orders(hours, syms, limit)
    return JSONResponse(items)
