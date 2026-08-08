# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: local read-only dashboard; trading keys and order actions never enter this layer.

from fastapi import Request
from fastapi.responses import JSONResponse
import psutil, shutil, json, os, socket, asyncio, subprocess, math, time, secrets, threading, re, platform, shlex, ipaddress
import requests
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from pathlib import Path
import sqlite3
from typing import List, Dict, Optional, Tuple

from ladder_dragon.ai.ai_runtime_status import read_runtime_status
from ladder_dragon.execution.maintenance_state import (
    DEFAULT_PATH as DEFAULT_MAINTENANCE_PATH,
    load_maintenance_state,
)
from ladder_dragon.ai.ai_control import (
    read_ai_control,
    resolve_ai_control_path,
    write_ai_control,
)
from ladder_dragon.execution.order_recovery import read_order_journal_telemetry
from ladder_dragon.execution.trade_accounting import DEFAULT_SPOT_FEE_PCT
from ladder_dragon.sqlite_safety import quote_sqlite_identifier
from product_version import PRODUCT_NAME, __version__
from ladder_dragon.execution.telegram_alerts import notify_binance_auth_error
from ladder_dragon.dashboard.app_factory import create_dashboard_app
from ladder_dragon.dashboard.dependencies import open_read_only_sqlite
from ladder_dragon.dashboard.services.accounting import base_asset_of
from ladder_dragon.dashboard.services.trade_summary import (
    fifo_realized_pnl as _fifo_realized_pnl,
)
from ladder_dragon.dashboard.services.host_telemetry import (
    load_history_payload,
    rolling_trade_volume_24h_usdt,
)
from ladder_dragon.dashboard.services.runtime_health import runtime_degraded_reason
from ladder_dragon.dashboard.services.user_stream import current_soak_epoch_metrics
from ladder_dragon.dashboard.services.binance_readonly import ReadOnlyBinanceClient
from ladder_dragon.deployment.status import read_deployment_status
APP_TZ = ZoneInfo("Asia/Almaty")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT / "FastAPI" / "pi-dashboard"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
HIST_FILE = DATA_DIR / "metrics.ndjson"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "PiDashboard/1.0"})
BINANCE_BASE = os.getenv("BINANCE_API_BASE", "https://api.binance.com").rstrip("/")
DASHBOARD_AUTH_TOKEN = os.getenv("DASHBOARD_AUTH_TOKEN", "")
DASHBOARD_TRUST_PROXY_AUTH = os.getenv("DASHBOARD_TRUST_PROXY_AUTH", "0") == "1"
DASHBOARD_PROXY_AUTH_SECRET = os.getenv("DASHBOARD_PROXY_AUTH_SECRET", "")
DASHBOARD_RATE_LIMIT_PER_MIN = max(1, int(os.getenv("DASHBOARD_RATE_LIMIT_PER_MIN", "360")))
_RATE_BUCKETS: Dict[str, deque] = defaultdict(deque)
_RATE_LOCK = threading.Lock()
_RATE_PRUNE_STATE = {"last": 0.0}
DASHBOARD_CSRF_TOKEN = secrets.token_urlsafe(32)
_BALANCE_CACHE: Dict[str, object] = {"ts": 0.0, "payload": None}
_BALANCE_CACHE_TTL_SEC = max(5.0, float(os.getenv("DASHBOARD_BALANCE_CACHE_SEC", "10")))
_BALANCE_CACHE_LOCK = threading.Lock()
_OPEN_ORDERS_CACHE: Dict[str, object] = {"ts": 0.0, "payload": None}
_OPEN_ORDERS_CACHE_TTL_SEC = max(3.0, float(os.getenv("DASHBOARD_OPEN_ORDERS_CACHE_SEC", "5")))
_OPEN_ORDERS_CACHE_LOCK = threading.Lock()
DASHBOARD_STALE_CACHE_MAX_SEC = max(
    30.0,
    float(os.getenv("DASHBOARD_STALE_CACHE_MAX_SEC", "300")),
)
DASHBOARD_USER_STREAM_STALE_SEC = max(
    30.0,
    float(os.getenv("DASHBOARD_USER_STREAM_STALE_SEC", "180")),
)
_OPS_CACHE: Dict[str, object] = {"ts": 0.0, "payload": None}
_OPS_CACHE_TTL_SEC = max(10.0, float(os.getenv("DASHBOARD_OPS_CACHE_SEC", "30")))
_OPS_CACHE_LOCK = threading.Lock()
GITHUB_REPOSITORY = os.getenv("DASHBOARD_GITHUB_REPOSITORY", "potekhinskill/Ladder-Dragon")
# Release update checks are intentionally pinned to the only canonical branch.
GITHUB_BRANCH = "main"
GITHUB_TOKEN = os.getenv("DASHBOARD_GITHUB_TOKEN", "")
GITHUB_UPDATE_CHECK_TTL_SEC = max(
    60.0,
    float(os.getenv("DASHBOARD_GITHUB_UPDATE_CHECK_SEC", "300")),
)
_GITHUB_UPDATE_CACHE: Dict[str, object] = {
    "ts": 0.0,
    "attempt_ts": 0.0,
    "last_error": None,
    "payload": None,
}
_GITHUB_UPDATE_CACHE_LOCK = threading.Lock()
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
DASHBOARD_AI_AGGREGATE_CACHE_SEC = max(
    5.0, float(os.getenv("DASHBOARD_AI_AGGREGATE_CACHE_SEC", "30"))
)
_AI_SUMMARY_CACHE: Dict[str, Dict[str, object]] = {}
_AI_SUMMARY_CACHE_LOCK = threading.Lock()
AI_RUNTIME_STATUS_FILE = Path(
    os.getenv("AI_RUNTIME_STATUS_FILE", "/run/mybot/ai_status.json")
)
BOT_MAINTENANCE_FILE = Path(
    os.getenv("BOT_MAINTENANCE_FILE", str(DEFAULT_MAINTENANCE_PATH))
)
AI_CONTROL_FILE = resolve_ai_control_path(os.getenv("AI_CONTROL_FILE"))
DASHBOARD_FOLLOW_BOT_PATHS = (
    os.getenv("DASHBOARD_FOLLOW_BOT_PATHS", "0") == "1"
)
BOT_SERVICE_ENV_FILE = Path(
    os.getenv("DASHBOARD_BOT_SERVICE_ENV", str(PROJECT_ROOT / ".env.service"))
)
HOST_HEALTH_STATUS_FILE = Path(
    os.getenv(
        "DASHBOARD_HOST_HEALTH_STATUS_FILE",
        "/run/pi-watchdog/host-health.json",
    )
)

# External telemetry failures may degrade a widget, but programming errors
# must still surface during tests instead of being hidden by a broad catch.
_DATA_SOURCE_ERRORS = (
    OSError,
    sqlite3.Error,
    requests.RequestException,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    ArithmeticError,
)


def _prune_rate_buckets(now: float) -> None:
    """Remove expired client keys while the caller holds ``_RATE_LOCK``."""
    if now - _RATE_PRUNE_STATE["last"] < 60:
        return
    cutoff = now - 60
    for stale_client, stale_bucket in list(_RATE_BUCKETS.items()):
        while stale_bucket and stale_bucket[0] <= cutoff:
            stale_bucket.popleft()
        if not stale_bucket:
            _RATE_BUCKETS.pop(stale_client, None)
    _RATE_PRUNE_STATE["last"] = now

@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(collector_loop())
    try:
        yield
    finally:
        task.cancel()


app = create_dashboard_app(lifespan)

GiB = 1024**3


def _database_unavailable_response() -> JSONResponse:
    """Return one sanitized retry contract for the dashboard read model."""
    return JSONResponse(
        {
            "ok": False,
            "error": "DATABASE_TEMPORARILY_UNAVAILABLE",
            "retryable": True,
        },
        status_code=503,
        headers={"Retry-After": "2"},
    )


@app.exception_handler(sqlite3.Error)
async def sqlite_temporarily_unavailable(
    _request: Request,
    exc: sqlite3.Error,
):
    """Expose transient read-model startup as retryable, never HTTP 500."""
    print(
        f"[DASHBOARD] DATABASE_TEMPORARILY_UNAVAILABLE "
        f"type={type(exc).__name__}",
        flush=True,
    )
    return _database_unavailable_response()


@app.middleware("http")
async def authenticate_and_rate_limit(request: Request, call_next):
    """Authenticate every API request and enforce a bounded per-client rate."""
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

        peer = request.client.host if request.client else "unknown"
        client = peer
        if proxy_authenticated:
            try:
                if ipaddress.ip_address(peer).is_loopback:
                    forwarded = request.headers.get("X-Real-IP", "")
                    client = str(ipaddress.ip_address(forwarded))
            except ValueError:
                client = peer
        now = time.monotonic()
        with _RATE_LOCK:
            _prune_rate_buckets(now)
            bucket = _RATE_BUCKETS[client]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= DASHBOARD_RATE_LIMIT_PER_MIN:
                return JSONResponse(
                    {"ok": False, "error": "rate limit exceeded"}, status_code=429, headers={"Retry-After": str(max(1, int(61 - (now - bucket[0]))))})
            bucket.append(now)

        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            host = request.headers.get("Host", "")
            scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)
            expected_origin = f"{scheme}://{host}"
            origin = request.headers.get("Origin", "")
            fetch_site = request.headers.get("Sec-Fetch-Site", "")
            csrf = request.headers.get("X-CSRF-Token", "")
            if content_type != "application/json":
                return JSONResponse({"ok": False, "error": "JSON content type required"}, status_code=415)
            if not origin or not secrets.compare_digest(origin, expected_origin):
                return JSONResponse({"ok": False, "error": "cross-origin request blocked"}, status_code=403)
            if fetch_site and fetch_site not in {"same-origin", "same-site"}:
                return JSONResponse({"ok": False, "error": "cross-site request blocked"}, status_code=403)
            if not csrf or not secrets.compare_digest(csrf, DASHBOARD_CSRF_TOKEN):
                return JSONResponse({"ok": False, "error": "CSRF token required"}, status_code=403)
    return await call_next(request)


@app.get("/api/security/csrf")
def csrf_token():
    """Return a process-local token only to an authenticated same-origin client."""
    return {"ok": True, "csrf_token": DASHBOARD_CSRF_TOKEN}

# ---- helpers for DB trades / PnL -------------------------------------------------

def get_db_path() -> str:
    # When explicitly enabled, the dashboard follows the trading process venue.
    # The status file contains no keys and is available only to the local user.
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
    """Load ai runtime status."""
    try:
        return read_runtime_status(AI_RUNTIME_STATUS_FILE)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _runtime_heartbeat_snapshot() -> Dict[str, object]:
    """Report bot heartbeat age instead of confusing it with service uptime."""
    runtime = _load_ai_runtime_status()
    try:
        maintenance = load_maintenance_state(BOT_MAINTENANCE_FILE)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        maintenance = None
    if maintenance is not None and maintenance.active:
        return {
            "state": "INTENTIONALLY_STOPPED",
            "updated_at": datetime.fromtimestamp(
                maintenance.updated_at_epoch, APP_TZ
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "age_sec": max(
                0.0, round(time.time() - maintenance.updated_at_epoch, 1)
            ),
            "fresh": False,
            "alive_fail_closed": True,
            "warning": maintenance.reason,
        }
    state = str(runtime.get("state") or "unknown")
    updated_raw = runtime.get("updated_at")
    if not isinstance(updated_raw, str) or not updated_raw.strip():
        return {"state": state, "updated_at": None, "age_sec": None, "fresh": False}
    try:
        updated = datetime.fromisoformat(updated_raw)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age_sec = max(
            0.0,
            (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds(),
        )
    except (TypeError, ValueError, OverflowError):
        return {"state": state, "updated_at": None, "age_sec": None, "fresh": False}
    blocked_states = {
        "AUTH_BACKOFF", "PREFLIGHT_BACKOFF", "IP_BLOCKED",
        "RECOVERY_BLOCKED", "INTENTIONALLY_STOPPED",
    }
    return {
        "state": state,
        "updated_at": updated.astimezone(APP_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "age_sec": round(age_sec, 1),
        "fresh": state == "RUNNING" and age_sec <= 90,
        "alive_fail_closed": state in blocked_states and age_sec <= 90,
        "warning": (
            "Trading is fail-closed pending operator attention"
            if state in blocked_states else None
        ),
    }


def _user_stream_snapshot(runtime: Dict[str, object]) -> Dict[str, object]:
    """Read sanitized snapshots from the independent read-only observer."""
    symbols = runtime.get("symbols")
    if not isinstance(symbols, list):
        symbols = []
    rows = []
    for raw_symbol in symbols:
        symbol = str(raw_symbol).strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{1,20}", symbol):
            continue
        path = Path(os.getenv("USER_STREAM_STATUS_DIR", "/var/lib/ladder-dragon/user-stream")) / f"user_stream_{symbol}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("stream health payload is not an object")
            stat = path.stat()
            transport_activity_at = float(
                payload.get("last_transport_activity_at") or stat.st_mtime
            )
            if (
                transport_activity_at <= 0
                or not math.isfinite(transport_activity_at)
            ):
                raise ValueError("invalid transport activity timestamp")
            age_sec = max(0, int(time.time() - transport_activity_at))
            reported_state = str(payload.get("state") or "unknown")
            stale = age_sec > DASHBOARD_USER_STREAM_STALE_SEC
            first_observed_at = float(
                payload.get("first_observed_at") or 0
            )
            if not math.isfinite(first_observed_at) or first_observed_at < 0:
                first_observed_at = 0.0
            cumulative_observation_hours = (
                max(0.0, time.time() - first_observed_at) / 3600
                if first_observed_at > 0 else 0.0
            )
            connected_at = float(payload.get("connected_at") or 0)
            if not math.isfinite(connected_at) or connected_at < 0:
                connected_at = 0.0
            current_session_hours = (
                max(0.0, time.time() - connected_at) / 3600
                if reported_state == "connected" and connected_at > 0
                else 0.0
            )
            soak_epoch = current_soak_epoch_metrics(payload, now=time.time())
            reconnects = int(payload.get("reconnects") or 0)
            idle_reconnects = int(payload.get("idle_reconnects") or 0)
            controlled_reconnects = int(
                payload.get("controlled_reconnect_drills") or 0
            )
            failure_reconnects = int(
                payload.get("transport_failure_reconnects") or 0
            )
            rows.append({
                "symbol": symbol,
                "available": True,
                "state": "stale" if stale else reported_state,
                "reported_state": reported_state,
                "stale": stale,
                "stale_after_sec": DASHBOARD_USER_STREAM_STALE_SEC,
                "age_sec": age_sec,
                "order_events": int(payload.get("order_events") or 0),
                "duplicates": int(payload.get("duplicates") or 0),
                "out_of_order_events": int(
                    payload.get("out_of_order_events") or 0
                ),
                "bad_frames": int(payload.get("bad_frames") or 0),
                "reconnects": reconnects,
                "planned_reconnects": idle_reconnects + controlled_reconnects,
                "failure_reconnects": failure_reconnects,
                "legacy_unclassified_reconnects": max(
                    0, reconnects - idle_reconnects
                    - controlled_reconnects - failure_reconnects
                ),
                "connection_attempts": int(
                    payload.get("connection_attempts") or 0
                ),
                "sessions": int(payload.get("sessions") or 0),
                "disconnects": int(payload.get("disconnects") or 0),
                # Keep the old field for API compatibility, but name the two
                # distinct clocks explicitly for the dashboard.
                "soak_hours": round(cumulative_observation_hours, 2),
                "cumulative_observation_hours": round(
                    cumulative_observation_hours, 2
                ),
                "current_session_hours": round(current_session_hours, 2),
                **soak_epoch,
                "last_error": (
                    str(payload.get("last_error"))
                    if payload.get("last_error") else None
                ),
                "last_event_at": payload.get("last_event_at"),
                "last_order_event_at": payload.get("last_order_event_at"),
                "last_transport_activity_at": transport_activity_at,
            })
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            rows.append({
                "symbol": symbol,
                "available": False,
                "state": "not_configured_or_not_started",
                "reported_state": None,
                "stale": True,
                "stale_after_sec": DASHBOARD_USER_STREAM_STALE_SEC,
                "age_sec": None,
                "order_events": 0,
                "duplicates": 0,
                "out_of_order_events": 0,
                "bad_frames": 0,
                "reconnects": 0,
                "planned_reconnects": 0,
                "failure_reconnects": 0,
                "legacy_unclassified_reconnects": 0,
                "connection_attempts": 0,
                "sessions": 0,
                "disconnects": 0,
                "soak_hours": 0.0,
                "cumulative_observation_hours": 0.0,
                "current_session_hours": 0.0,
                "soak_epoch_id": None,
                "soak_epoch_hours": 0.0,
                "soak_epoch_reconnects": 0,
                "soak_epoch_order_events": 0,
                "last_error": None,
                "last_event_at": None,
                "last_order_event_at": None,
                "last_transport_activity_at": None,
            })
    return {
        "mode": "shadow_notification_only",
        "rest_authoritative": True,
        "streams": rows,
    }


def _runtime_data_path(runtime: Dict, name: str, fallback: str) -> Path:
    """Handle runtime data path."""
    if DASHBOARD_FOLLOW_BOT_PATHS:
        value = runtime.get("paths", {}).get(name)
        if isinstance(value, str) and value.strip():
            return Path(value.strip())
    return Path(fallback)

def _open_db():
    path = get_db_path()
    # The dashboard is a read model. URI read-only mode prevents a restart race
    # from creating an empty database before the trading process initializes it.
    con = open_read_only_sqlite(Path(path).expanduser(), timeout=5.0)
    con.execute("PRAGMA query_only=ON")
    return con, path

def _has_column(con: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        safe_table = quote_sqlite_identifier(table)
        cur = con.execute(f"PRAGMA table_info({safe_table});")
        cols = [r["name"] for r in cur.fetchall()]
        return col in cols
    except sqlite3.Error:
        return False

def _ts_to_s(ts_val) -> int:
    # supports ms and s
    try:
        ts = int(ts_val)
        return ts // 1000 if ts > 10_000_000_000 else ts
    except (TypeError, ValueError):
        return 0

def _fee_pct_default() -> float:
    try:
        return float(os.getenv("BOT_FEE_PCT", str(DEFAULT_SPOT_FEE_PCT)))
    except (TypeError, ValueError):
        return float(DEFAULT_SPOT_FEE_PCT)

def _load_trades(con: sqlite3.Connection, symbols: Optional[List[str]] = None) -> List[sqlite3.Row]:
    sym_filter = ""
    args: List = []
    if symbols:
        qs = ",".join("?" for _ in symbols)
        sym_filter = f" AND symbol IN ({qs})"
        args.extend(symbols)

    # Migration 006 exposes exact text as the authoritative accounting source.
    # Numeric JSON conversion happens only after the exact value is selected.
    sql = f"""
    SELECT
      symbol, side, price_text AS price, gross_qty_text AS qty,
      net_qty_text AS net_qty,
      commission_asset, commission_amount_text AS commission_amount,
      commission_quote_text AS fee_quote,
      commission_value_status AS commission_status,
      CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
    FROM trades_exact
    WHERE 1=1 {sym_filter}
    ORDER BY ts_s ASC
    """
    return list(con.execute(sql, args).fetchall())

def _api_creds() -> Tuple[str, str]:
    """Read dedicated read-only credentials on demand; do not retain globals."""
    return (
        os.getenv("DASHBOARD_BINANCE_API_KEY", "").strip(),
        os.getenv("DASHBOARD_BINANCE_API_SECRET", "").strip(),
    )


def ensure_api_creds() -> bool:
    key, secret = _api_creds()
    return bool(key and secret)


_BINANCE_READER = ReadOnlyBinanceClient(
    session=SESSION,
    base_url=BINANCE_BASE,
    credentials=_api_creds,
    auth_error=notify_binance_auth_error,
)

# ---- Binance helpers & equity-PNL ------------------------------------------------

def _pub_get(path: str, params=None, timeout: float = 10.0):
    r = SESSION.get(BINANCE_BASE + path, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _signed(method: str, path: str, params=None, timeout: float = 10.0):
    return _BINANCE_READER.signed(method, path, params=params, timeout=timeout)

def price_now(symbol: str) -> float:
    j = _pub_get("/api/v3/ticker/price", {"symbol": symbol})
    return float(j["price"])

def price_at(symbol: str, ts_ms: int) -> float:
    minute_ms = ts_ms - (ts_ms % 60_000)
    j = _pub_get("/api/v3/klines", {"symbol": symbol, "interval": "1m", "startTime": minute_ms, "limit": 1})
    if not j:
        raise RuntimeError("historical price is unavailable")
    if int(j[0][0]) != minute_ms:
        raise RuntimeError("historical price timestamp does not match")
    return float(j[0][1])  # open

def account_balances_now() -> Dict[str, float]:
    """Handle account balances now."""
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
    """Handle account balances snapshot."""
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
        "stale": False,
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
    """Handle account open orders snapshot."""
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
        "stale": False,
        "updated_at": now_str(),
        "venue": BINANCE_BASE,
        "count": len(orders),
        "orders": orders,
    }
    with _OPEN_ORDERS_CACHE_LOCK:
        _OPEN_ORDERS_CACHE["ts"] = now
        _OPEN_ORDERS_CACHE["payload"] = payload
    return payload


def _stale_binance_snapshot(
    cache: Dict[str, object],
    lock: threading.Lock,
    warning: str,
) -> Optional[Dict[str, object]]:
    """Return a clearly marked recent snapshot during a transient Binance fault."""
    now = time.monotonic()
    with lock:
        cached = cache.get("payload")
        cached_at = float(cache.get("ts", 0.0))
        age = max(0.0, now - cached_at)
        if not isinstance(cached, dict) or age > DASHBOARD_STALE_CACHE_MAX_SEC:
            return None
        payload = dict(cached)
    payload.update({
        "ok": True,
        "stale": True,
        "stale_age_sec": round(age, 1),
        "warning": warning,
    })
    return payload


def _verified_cost_basis_from_lots(
    symbol: str,
    account_quantity: Decimal,
) -> Dict[str, object]:
    """Return read-only cost basis only when sourced lots cover the account."""
    unavailable: Dict[str, object] = {
        "covered": False,
        "average_price": None,
        "covered_quantity": "0",
        "uncovered_quantity": format(max(Decimal("0"), account_quantity), "f"),
        "status": "unverified_inventory_history",
        "reason": "verified inventory lots are unavailable",
    }
    try:
        con, _ = _open_db()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return unavailable
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='inventory_lots'"
        ).fetchone()
        if not exists:
            return unavailable
        columns = {
            str(row[1])
            for row in con.execute('PRAGMA table_info("inventory_lots")')
        }
        required = {
            "lot_id",
            "qty",
            "price",
            "opened_at",
            "source_order_id",
            "status",
        }
        if not required.issubset(columns):
            return unavailable
        trade_source = (
            quote_sqlite_identifier("source_trade_id")
            if "source_trade_id" in columns else "''"
        )
        rows = con.execute(
            "SELECT qty,price,source_order_id,"
            f"{trade_source} AS source_trade_id "
            "FROM inventory_lots WHERE symbol=? AND status='OPEN' "
            "ORDER BY opened_at,lot_id",
            (symbol.upper(),),
        ).fetchall()
        covered_quantity = Decimal("0")
        covered_cost = Decimal("0")
        invalid_rows = 0
        for qty_text, price_text, source_order_id, source_trade_id in rows:
            quantity = Decimal(str(qty_text))
            price = Decimal(str(price_text))
            sourced = bool(
                str(source_order_id or "").strip()
                or str(source_trade_id or "").strip()
            )
            if (
                not quantity.is_finite()
                or not price.is_finite()
                or quantity <= 0
                or price <= 0
                or not sourced
            ):
                invalid_rows += 1
                continue
            covered_quantity += quantity
            covered_cost += quantity * price
        tolerance_pct = Decimal(
            os.getenv("BOT_COST_BASIS_QTY_TOLERANCE_PCT", "0.002")
        )
        if not tolerance_pct.is_finite() or tolerance_pct < 0:
            return unavailable
        tolerance = max(
            Decimal("0.00000001"),
            account_quantity * tolerance_pct,
        )
        delta = account_quantity - covered_quantity
        covered = (
            invalid_rows == 0
            and covered_quantity > 0
            and abs(delta) <= tolerance
        )
        return {
            "covered": covered,
            "average_price": (
                covered_cost / covered_quantity if covered else None
            ),
            "covered_quantity": format(covered_quantity, "f"),
            "uncovered_quantity": format(max(Decimal("0"), delta), "f"),
            "status": (
                "verified_full_inventory"
                if covered else "partial_inventory_lots"
                if covered_quantity > 0 else "unverified_inventory_history"
            ),
            "reason": (
                "covered"
                if covered else "inventory lots contain invalid provenance"
                if invalid_rows else "account quantity exceeds sourced lots"
            ),
        }
    except (
        ArithmeticError,
        InvalidOperation,
        OSError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ):
        return unavailable
    finally:
        con.close()


def _order_journal_snapshot(runtime: Dict[str, object]) -> Dict[str, object]:
    """Return sanitized runtime telemetry without opening the live WAL DB."""
    runtime_snapshot = runtime.get("order_journal")
    if isinstance(runtime_snapshot, dict):
        snapshot = dict(runtime_snapshot)
        latest = snapshot.get("latest")
        if isinstance(latest, dict):
            item = dict(latest)
            try:
                item["updated_at"] = datetime.fromtimestamp(
                    float(item.pop("updated_at_epoch")), APP_TZ
                ).strftime("%Y-%m-%d %H:%M:%S")
            except (KeyError, OSError, OverflowError, TypeError, ValueError):
                item["updated_at"] = None
            snapshot["latest"] = item
        snapshot["source"] = "runtime"
        return snapshot

    # A stopped or older bot may not have exported telemetry yet. Keep this
    # compatibility read fail-closed: the dashboard never receives DB writes.
    paths = runtime.get("paths", {}) if isinstance(runtime.get("paths"), dict) else {}
    path = Path(str(paths.get("order_journal") or os.getenv(
        "BOT_ORDER_JOURNAL", "/home/bot/apps/binance_bot/db/order_intents.sqlite3"
    )))
    snapshot = read_order_journal_telemetry(path)
    snapshot["source"] = "database"
    latest = snapshot.get("latest")
    if isinstance(latest, dict):
        item = dict(latest)
        try:
            item["updated_at"] = datetime.fromtimestamp(
                float(item.pop("updated_at_epoch")), APP_TZ
            ).strftime("%Y-%m-%d %H:%M:%S")
        except (KeyError, OSError, OverflowError, TypeError, ValueError):
            item["updated_at"] = None
        snapshot["latest"] = item
    return snapshot


def _bot_service_config() -> Dict[str, object]:
    """Read only non-secret service settings used to explain a stopped bot."""
    allowed = {
        "BOT_SERVICE_VENUE",
        "BOT_SERVICE_EXECUTION",
        "BOT_SERVICE_SYMBOLS",
        "BOT_SERVICE_EXTRA_ARGS",
        "BOT_SERVICE_AUTO_OCO_HOLDINGS",
    }
    values: Dict[str, str] = {}
    try:
        for raw_line in BOT_SERVICE_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() not in allowed:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key.strip()] = value
    except OSError:
        return {}

    symbols = [
        symbol.strip().upper()
        for symbol in values.get("BOT_SERVICE_SYMBOLS", "").split(",")
        if symbol.strip()
    ]
    config: Dict[str, object] = {
        "venue": values.get("BOT_SERVICE_VENUE", "").lower() or None,
        "execution_mode": values.get("BOT_SERVICE_EXECUTION", "").upper() or None,
        "symbols": symbols,
        "auto_oco_holdings": values.get("BOT_SERVICE_AUTO_OCO_HOLDINGS", "0") == "1",
    }
    try:
        arguments = shlex.split(values.get("BOT_SERVICE_EXTRA_ARGS", ""))
    except ValueError:
        arguments = []
    for index, argument in enumerate(arguments[:-1]):
        if argument in {"--cap-floor-usdt", "--cap-ceil-usdt"}:
            try:
                config[argument.removeprefix("--").replace("-", "_")] = float(arguments[index + 1])
            except ValueError:
                continue
    return config


def _bot_execution_context(runtime: Dict[str, object]) -> Dict[str, object]:
    """Resolve service state without turning account dust into trading symbols."""
    configured = _bot_service_config()
    service_state = service_active("mybot") or "unknown"
    runtime_symbols = runtime.get("symbols", []) if isinstance(runtime.get("symbols"), list) else []
    symbols = configured.get("symbols") or [
        str(item).upper() for item in runtime_symbols if item
    ]
    configured_mode = configured.get("execution_mode")
    runtime_mode = str(runtime.get("execution_mode") or "").upper() or None
    if service_state in {"inactive", "failed", "deactivating"}:
        execution_mode = "STOPPED"
    else:
        execution_mode = runtime_mode or configured_mode or "UNKNOWN"
    return {
        "service_state": service_state,
        "execution_mode": execution_mode,
        "configured_execution_mode": configured_mode,
        "venue": runtime.get("venue") or configured.get("venue") or BINANCE_BASE,
        "symbols": symbols,
        "cap_floor_usdt": configured.get("cap_floor_usdt"),
        "cap_ceil_usdt": configured.get("cap_ceil_usdt"),
        "auto_oco_holdings": bool(configured.get("auto_oco_holdings", False)),
    }


def trading_overview_snapshot() -> Dict[str, object]:
    """Handle trading overview snapshot."""
    runtime = _load_ai_runtime_status()
    balances = account_balances_snapshot()
    orders = account_open_orders_snapshot()
    balance_by_asset = {str(row["asset"]).upper(): row for row in balances.get("assets", [])}
    execution = _bot_execution_context(runtime)
    symbols = execution["symbols"]
    order_rows = orders.get("orders", []) if isinstance(orders.get("orders"), list) else []
    journal = _order_journal_snapshot(runtime)
    journal_latest = journal.get("latest") if isinstance(journal.get("latest"), dict) else {}
    journal_managed = {
        str(row.get("symbol") or "").upper(): row
        for row in journal.get("managed_buys", [])
        if isinstance(row, dict) and row.get("symbol")
    }
    journal_exchange_mismatches: list[dict[str, object]] = []
    positions = []
    for symbol in symbols:
        base = base_asset_of(symbol)
        balance = balance_by_asset.get(base, {})
        try:
            quantity_exact = Decimal(str(balance.get("total", "0") or "0"))
        except (ArithmeticError, InvalidOperation, TypeError, ValueError):
            quantity_exact = Decimal("0")
        if not quantity_exact.is_finite() or quantity_exact < 0:
            quantity_exact = Decimal("0")
        quantity = float(quantity_exact)
        current = balance.get("price_usdt")
        if current is None:
            try:
                current = price_now(symbol)
            except _DATA_SOURCE_ERRORS:
                current = None
        try:
            current_exact = (
                Decimal(str(current))
                if current is not None else None
            )
            if current_exact is not None and (
                not current_exact.is_finite() or current_exact <= 0
            ):
                current_exact = None
        except (ArithmeticError, InvalidOperation, TypeError, ValueError):
            current_exact = None
        cost_basis = _verified_cost_basis_from_lots(
            symbol,
            quantity_exact,
        )
        average_exact = (
            cost_basis.get("average_price")
            if cost_basis.get("covered") else None
        )
        value_exact = (
            quantity_exact * current_exact
            if current_exact is not None else None
        )
        unrealized_exact = (
            (current_exact - average_exact) * quantity_exact
            if current_exact is not None
            and isinstance(average_exact, Decimal)
            else None
        )
        drawdown_exact = (
            (current_exact / average_exact - Decimal("1")) * Decimal("100")
            if current_exact is not None
            and isinstance(average_exact, Decimal)
            and average_exact > 0
            else None
        )
        legs = [row for row in order_rows if row.get("symbol") == symbol and row.get("side") == "SELL"]
        tp_legs = [
            row for row in legs
            if str(row.get("type") or "").upper() in {"LIMIT", "LIMIT_MAKER"}
        ]
        stop_legs = [
            row for row in legs
            if str(row.get("type") or "").upper()
            in {"STOP_LOSS", "STOP_LOSS_LIMIT"}
        ]
        tp_quantity = sum(
            float(row.get("remaining_qty", 0.0) or 0.0) for row in tp_legs
        )
        stop_quantity = sum(
            float(row.get("remaining_qty", 0.0) or 0.0) for row in stop_legs
        )
        protected_quantity = min(tp_quantity, stop_quantity)
        managed_row = journal_managed.get(symbol, {})
        try:
            managed_quantity = max(
                0.0,
                min(quantity, float(managed_row.get("quantity") or 0)),
            )
        except (TypeError, ValueError):
            managed_quantity = 0.0
        legacy_quantity = max(0.0, quantity - managed_quantity)
        has_legacy_inventory = legacy_quantity > 1e-12
        journal_protected = int(managed_row.get("protected_buys") or 0) > 0
        exact_exchange_protection = (
            bool(tp_legs)
            and bool(stop_legs)
            and protected_quantity + 1e-12 >= managed_quantity
        )
        journal_exchange_mismatch = (
            managed_quantity > 1e-12
            and journal_protected
            and not exact_exchange_protection
        )
        if journal_exchange_mismatch:
            journal_exchange_mismatches.append({
                "symbol": symbol,
                "journal_state": "PROTECTED",
                "exchange_state": "MISSING_OR_INCOMPLETE_OCO",
                "managed_quantity": round(managed_quantity, 8),
                "protected_quantity": round(protected_quantity, 8),
            })
        try:
            latest_executed_quantity = float(journal_latest.get("executed_qty") or 0)
        except (TypeError, ValueError):
            latest_executed_quantity = 0.0
        latest_unprotected_fill = (
            str(journal_latest.get("symbol") or "").upper() == symbol
            and str(journal_latest.get("side") or "").upper() == "BUY"
            and str(journal_latest.get("status") or "").upper()
            in {"FILLED", "PARTIALLY_FILLED", "PROTECTION_PENDING"}
            and latest_executed_quantity > 0
        )
        legacy_unmanaged = False
        if quantity <= 1e-12:
            protection_state = "not_needed"
        elif journal_exchange_mismatch:
            protection_state = "journal_exchange_mismatch"
        elif managed_quantity > 1e-12 and exact_exchange_protection:
            protection_state = (
                "managed_confirmed_legacy_unmanaged"
                if has_legacy_inventory else "confirmed"
            )
        elif managed_quantity > 1e-12:
            protection_state = "missing_protection"
        elif legs:
            protection_state = "pending"
        elif latest_unprotected_fill:
            protection_state = "pending"
        elif not execution.get("auto_oco_holdings"):
            # Holdings which predate this bot lifecycle are deliberately outside
            # attach-on-fill protection. Report that policy explicitly instead
            # of implying that the live gap watchdog failed.
            protection_state = "legacy_unmanaged"
            legacy_unmanaged = True
        else:
            protection_state = "not_checked"
        positions.append({
            "symbol": symbol, "base_asset": base, "quantity": round(quantity, 8),
            "managed_quantity": round(managed_quantity, 8),
            "legacy_quantity": round(legacy_quantity, 8),
            "average_entry_usdt": (
                round(float(average_exact), 8)
                if isinstance(average_exact, Decimal) else None
            ),
            "current_price_usdt": (
                round(float(current_exact), 8)
                if current_exact is not None else None
            ),
            "value_usdt": (
                round(float(value_exact), 2)
                if value_exact is not None else None
            ),
            "unrealized_pnl_usdt": (
                round(float(unrealized_exact), 2)
                if unrealized_exact is not None else None
            ),
            "drawdown_pct": (
                round(float(drawdown_exact), 2)
                if drawdown_exact is not None else None
            ),
            "pnl_scope": (
                "full_account_inventory"
                if cost_basis.get("covered") else "unavailable"
            ),
            "protection": {
                "state": protection_state,
                "tp": [row.get("price") for row in legs if row.get("type") == "LIMIT_MAKER"],
                "stop": [row.get("stop_price") for row in legs if row.get("type") == "STOP_LOSS_LIMIT"],
                "locked_quantity": round(protected_quantity, 8),
                "gap_watchdog": (
                    "managed_lot_armed_only"
                    if protection_state == "managed_confirmed_legacy_unmanaged"
                    else "armed" if protection_state == "confirmed"
                    else "not_applicable_legacy_inventory" if legacy_unmanaged
                    else "warning"
                ),
                "classification": (
                    "managed_and_legacy_inventory"
                    if managed_quantity > 1e-12 and legacy_quantity > 1e-12
                    else "legacy_inventory" if legacy_unmanaged
                    else "managed_inventory"
                ),
                "managed_by_bot": managed_quantity > 1e-12,
                "managed_state": (
                    "confirmed"
                    if managed_quantity > 1e-12
                    and exact_exchange_protection
                    else "missing_or_incomplete"
                    if managed_quantity > 1e-12
                    else "not_applicable"
                ),
                "legacy_state": (
                    "unmanaged_unprotected"
                    if has_legacy_inventory else "not_applicable"
                ),
                "journal_exchange_mismatch": journal_exchange_mismatch,
                "cost_basis_status": cost_basis.get("status"),
                "cost_basis_covered_quantity": (
                    cost_basis.get("covered_quantity")
                ),
                "cost_basis_uncovered_quantity": (
                    cost_basis.get("uncovered_quantity")
                ),
                "cost_basis_reason": cost_basis.get("reason"),
                "cost_basis_action": (
                    "preview_only_import_required"
                    if not cost_basis.get("covered") else None
                ),
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
    latest_open = max(
        order_rows,
        key=lambda row: (
            int(row.get("updated_at") or 0),
            str(row.get("order_id") or ""),
        ),
        default=None,
    )
    if latest_open is not None:
        requested = float(latest_open.get("orig_qty", 0.0) or 0.0)
        executed = float(latest_open.get("executed_qty", 0.0) or 0.0)
        last_order = {
            "symbol": latest_open.get("symbol"),
            "side": latest_open.get("side"),
            "status": latest_open.get("status"),
            "order_id": latest_open.get("order_id"),
            "executed_qty": executed,
            "quantity": requested,
            "partial_fill": executed > 0 and requested > 0 and executed < requested,
            "latency_ms": None,
            "commission_usdt": None,
            "updated_at": datetime.fromtimestamp(
                int(latest_open.get("updated_at") or 0), APP_TZ
            ).strftime("%Y-%m-%d %H:%M:%S"),
        }
    else:
        last_order = journal.get("latest")
    reconciliation_delta = risk.get("reconciliation_delta")
    return {
        "ok": True,
        "updated_at": now_str(),
        "venue": execution["venue"],
        "execution_mode": execution["execution_mode"],
        "configured_execution_mode": execution["configured_execution_mode"],
        "service_state": execution["service_state"],
        "symbols": symbols,
        "free_usdt": round(free_usdt, 2),
        "reserve_usdt": risk_limits.get("reserve_usdt"),
        "caps": {
            "per_order_usdt": risk.get("current_cap_per_order_usdt") or execution.get("cap_ceil_usdt"),
            "operator_hard_usdt": risk.get("operator_cap_per_order_usdt") or execution.get("cap_ceil_usdt"),
            "configured_floor_usdt": execution.get("cap_floor_usdt"),
            "per_symbol": risk.get("symbol_caps_usdt", {}),
            "portfolio_usdt": risk_limits.get("portfolio_cap_usdt"),
        },
        "positions": positions,
        "orders": {
            "open": orders.get("count", 0),
            "cancelled": journal.get("cancelled"),
            "pending": journal.get("pending"),
            # Unknown journal data must remain visibly unknown. Converting it
            # to zero would falsely claim that reconciliation is complete.
            "journal_available": journal.get("available") is True,
            "journal_reason": journal.get("reason"),
            "journal_source": journal.get("source"),
            "lifecycle": journal.get("lifecycle", {}),
            "journal_exchange_mismatches": journal_exchange_mismatches,
        },
        "last_order": last_order,
        "reanchor": (
            runtime.get("reanchor", {})
            if isinstance(runtime.get("reanchor"), dict)
            else {}
        ),
        "prediction": (
            runtime.get("prediction", {})
            if isinstance(runtime.get("prediction"), dict)
            else {}
        ),
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
    except _DATA_SOURCE_ERRORS as exc:
        print(f"[DASHBOARD] TRADING_OVERVIEW_FAILED type={type(exc).__name__}", flush=True)
        return JSONResponse({"ok": False, "error": "TRADING_OVERVIEW_FAILED"}, status_code=503)

# ---- Approx equity from DB (no API keys) ----------------------------------------

def _approx_equity_now_from_db(rows: List[sqlite3.Row], symbols_list: Optional[List[str]], fee_pct: float) -> Dict:
    """Handle approx equity now from db."""
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
        fee_q = float(r["fee_quote"])
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

    # Fetch current prices for every asset that appears in the account.
    assets = {k for k,v in pos.items() if abs(v) > 0} | {"BNB"}
    prices: Dict[str, float] = {"USDT": 1.0}
    for a in list(assets):
        if a == "USDT":
            continue
        try:
            prices[a] = price_now(f"{a}USDT")
        except _DATA_SOURCE_ERRORS:
            prices[a] = 0.0

    # Account for commissions paid in BNB, never below zero.
    p_bnb = prices.get("BNB", 0.0)
    if p_bnb > 0 and fee_bnb_usdt_total > 0:
        pos["BNB"] = max(0.0, pos.get("BNB", 0.0) - (fee_bnb_usdt_total / p_bnb))

    # Clamp negative balances for every asset, including USDT and BNB.
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
    """Handle equity pnl usdt."""
    # Restrict window deltas and volumes to the requested symbols when present.
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

    # Exact method using signed account credentials.
    try:
        bals_now = account_balances_now()
        if sym_set:
            allowed_bases = {base_asset_of(s) for s in sym_set}
            assets = set(["USDT", "BNB"]) | allowed_bases
        else:
            assets = set(bals_now.keys()) | set(["USDT", "BNB"])

        # Current prices.
        p_now: Dict[str, float] = {"USDT": 1.0}
        for a in list(assets):
            if a == "USDT": continue
            sym = f"{a}USDT"
            try: p_now[a] = price_now(sym)
            except _DATA_SOURCE_ERRORS: p_now[a] = 0.0

        # Historical prices.
        p_then: Dict[str, float] = {"USDT": 1.0}
        for a in list(assets):
            if a == "USDT": continue
            sym = f"{a}USDT"
            p_then[a] = price_at(sym, cutoff_ms)

        # Restrict current balances.
        q1 = {a: bals_now.get(a, 0.0) for a in assets}

        # Reconstruct historical balances.
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
    except _DATA_SOURCE_ERRORS:
        # Current portfolio value can remain visible, but historical change
        # must not use the current price as a substitute for missing history.
        approx_now = _approx_equity_now_from_db(rows, symbols_list, fee_pct)
        eq_now  = approx_now.get("equity_now_usdt")

        return {
            "method": "unavailable-historical-price",
            "equity_now_usdt": eq_now,
            "equity_then_usdt": None,
            "equity_pnl_usdt": None,
            "equity_pct": None,
            "buy_volume_usdt": round(buy_usdt, 2),
            "sell_volume_usdt": round(sell_usdt, 2),
            "fees_usdt": round(fees_usdt, 2),
            "equity_assets": approx_now.get("assets"),
            "equity_now_usdt_approx": eq_now,
        }

# ------------------- system helpers (original) ------------------------------------

def run_command(*args: str, timeout=5):
    """Handle run command."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 1, "COMMAND_FAILED"

def now_local():
    return datetime.now(APP_TZ)

def now_str():
    return now_local().strftime("%Y-%m-%d %H:%M:%S")

def read_temp_c():
    rc,out = run_command("vcgencmd", "measure_temp")
    if rc==0 and "temp=" in out:
        try:
            return float(out.split("=",1)[1].split("'")[0])
        except (IndexError, TypeError, ValueError):
            pass
    for p in ("/sys/class/thermal/thermal_zone0/temp","/sys/devices/virtual/thermal/thermal_zone0/temp"):
        try:
            with open(p) as f:
                v = f.read().strip()
                val = float(v)/1000.0 if float(v)>200 else float(v)
                return round(val,1)
        except (OSError, TypeError, ValueError):
            continue
    return None

def _parse_throttled_raw(raw: str):
    if "throttled=0x" not in raw:
        return {
            "supported": False,
            "raw": None,
            "under_voltage_now": None,
            "freq_capped_now": None,
            "throttled_now": None,
            "temp_limit_now": None,
            "under_voltage_hist": None,
            "freq_capped_hist": None,
            "throttled_hist": None,
            "temp_limit_hist": None,
        }
    raw = raw.strip()
    try:
        hexstr = raw.split("0x",1)[1]
        val = int(hexstr,16)
    except (IndexError, TypeError, ValueError):
        val = 0
    def b(n): return bool((val>>n)&1)
    return {
        "supported": True,
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


def parse_throttled():
    rc,out = run_command("vcgencmd", "get_throttled")
    if rc == 0 and "throttled=0x" in out:
        return _parse_throttled_raw(out)
    try:
        payload = json.loads(HOST_HEALTH_STATUS_FILE.read_text(encoding="utf-8"))
        age_sec = time.time() - float(payload["updated_at_epoch"])
        if not 0 <= age_sec <= 900:
            raise ValueError("stale host health status")
        parsed = _parse_throttled_raw(str(payload.get("throttled_raw") or ""))
        parsed["source"] = "sanitized_watchdog_probe"
        parsed["age_sec"] = round(age_sec, 1)
        return parsed
    except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
        return _parse_throttled_raw("")

def network_ok():
    try:
        with socket.create_connection(("1.1.1.1",53), 0.5): pass
        return True
    except (OSError, TimeoutError):
        return False

def mounts_info():
    res = []
    try:
        if os.path.exists("/proc/mounts"):
            with open("/proc/mounts") as f:
                rows = (line.split() for line in f)
                for parts in rows:
                    if len(parts) >= 4:
                        dev, mnt, fstype, opts = parts[:4]
                        if mnt in ("/", "/tmp", "/var/tmp", "/mnt/usb1"):
                            res.append({"mountpoint": mnt, "fs": fstype, "opts": opts})
        else:
            # psutil is available on Linux, macOS, Windows and WSL.
            for part in psutil.disk_partitions(all=False):
                if part.mountpoint in {"/", "/tmp", "/var/tmp", "/mnt/usb1"} or part.mountpoint == os.path.abspath(os.sep):
                    res.append({"mountpoint": part.mountpoint, "fs": part.fstype, "opts": part.opts})
    except (OSError, ValueError, TypeError):
        pass
    return res

def service_active(name: str):
    if name not in {"mybot", "pi-healthd", "pi-watchdog-v3.timer"}:
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
    except (IndexError, TypeError, ValueError):
        pass
    return count


def _command_value(*args: str) -> str:
    """Handle command value."""
    _rc, output = run_command(*args, timeout=3)
    return output.strip().splitlines()[0].strip() if output.strip() else ""


def _systemd_service_snapshot(name: str) -> Dict[str, object]:
    """Handle systemd service snapshot."""
    if name not in {"mybot", "pi-healthd", "pi-watchdog-v3.timer"}:
        return {"state": "invalid"}
    _rc, output = run_command(
        "systemctl", "show", name,
        "-p", "ActiveState", "-p", "SubState", "-p", "ActiveEnterTimestamp",
        "-p", "ActiveEnterTimestampMonotonic", "-p", "NRestarts",
        "-p", "UnitFileState",
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
        "enabled": values.get("UnitFileState") == "enabled",
    }


def _ntp_snapshot() -> Dict[str, object]:
    """Handle ntp snapshot."""
    if not shutil.which("timedatectl"):
        return {"synchronized": None, "service": "unavailable"}
    synced = _command_value("timedatectl", "show", "-p", "NTPSynchronized", "--value").lower()
    service = _command_value("timedatectl", "show", "-p", "NTPService", "--value")
    return {
        "synchronized": synced in {"yes", "true", "1"},
        "service": service or None,
    }


def _binance_latency_snapshot() -> Dict[str, object]:
    """Handle binance latency snapshot."""
    started = time.monotonic()
    try:
        payload = _pub_get("/api/v3/time", timeout=5.0)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        server_ms = payload.get("serverTime") if isinstance(payload, dict) else None
        offset_ms = round(float(server_ms) - time.time() * 1000, 1) if server_ms is not None else None
        return {"ok": True, "latency_ms": elapsed_ms, "offset_ms": offset_ms, "checked_at": now_str(), "error": None}
    except _DATA_SOURCE_ERRORS as exc:
        return {"ok": False, "latency_ms": None, "offset_ms": None, "checked_at": now_str(), "error": type(exc).__name__}


def _backup_snapshot() -> Dict[str, object]:
    """Handle backup snapshot."""
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
    """Handle usb snapshot."""
    mountpoint = os.getenv("DASHBOARD_BACKUP_MOUNT", "/mnt/usb1")
    findmnt_target = _command_value("findmnt", "-T", mountpoint, "-no", "TARGET") if shutil.which("findmnt") else ""
    mounted = findmnt_target == mountpoint or (not findmnt_target and Path(mountpoint).exists() and platform.system() != "Linux")
    options = _command_value("findmnt", "-T", mountpoint, "-no", "OPTIONS") if findmnt_target else ("unknown" if mounted else "")
    writable = mounted and "ro" not in {item.strip() for item in options.split(",")}
    payload: Dict[str, object] = {"mountpoint": mountpoint, "mounted": mounted, "writable": writable, "options": options, "free_gib": None, "used_percent": None}
    if mounted:
        try:
            usage = shutil.disk_usage(mountpoint)
            payload.update({"free_gib": round(usage.free / GiB, 3), "used_percent": round(usage.used * 100 / usage.total, 1)})
        except OSError as exc:
            payload["error"] = type(exc).__name__
    return payload


def _host_snapshot() -> Dict[str, object]:
    """Return portable host metadata; Raspberry-only probes remain optional."""
    return {
        "system": platform.system() or "unknown",
        "release": platform.release() or None,
        "machine": platform.machine() or None,
        "python": platform.python_version(),
        "root_mount": os.path.abspath(os.sep),
        "is_raspberry_pi": Path("/proc/device-tree/model").exists() or bool(shutil.which("vcgencmd")),
    }

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
    except (OSError, TypeError, ValueError):
        pass

async def collector_loop():
    await collect_once()
    while True:
        try:
            await collect_once()
        except (OSError, ValueError, TypeError):
            pass
        await asyncio.sleep(60)

def _git_head_commit() -> Optional[str]:
    """Return the locally deployed commit without exposing shell output."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        value = result.stdout.strip()
        return value if re.fullmatch(r"[0-9a-f]{40}", value) else None
    except (OSError, subprocess.SubprocessError):
        return None


def _github_update_snapshot() -> Dict[str, object]:
    """Check GitHub at the configured cadence and label old evidence stale."""
    now_mono = time.monotonic()
    with _GITHUB_UPDATE_CACHE_LOCK:
        cached = _GITHUB_UPDATE_CACHE.get("payload")
        cached_at = float(_GITHUB_UPDATE_CACHE.get("ts", 0.0))
        attempt_at = float(
            _GITHUB_UPDATE_CACHE.get("attempt_ts", cached_at)
        )
        last_error = _GITHUB_UPDATE_CACHE.get("last_error")
        if (
            cached is not None
            and now_mono - attempt_at < GITHUB_UPDATE_CHECK_TTL_SEC
        ):
            result = dict(cached)
            result["cache_age_sec"] = max(
                0, int(now_mono - cached_at)
            )
            result["stale"] = bool(last_error and result.get("ok"))
            result["error"] = last_error or result.get("error")
            return result

    checked_at = now_str()
    current_commit = _git_head_commit()
    payload: Dict[str, object] = {
        "ok": False,
        "repository": GITHUB_REPOSITORY,
        "branch": GITHUB_BRANCH,
        "current_commit": current_commit,
        "remote_commit": None,
        "update_available": None,
        "checked_at": checked_at,
        "cache_ttl_sec": int(GITHUB_UPDATE_CHECK_TTL_SEC),
        "cache_age_sec": 0,
        "stale": False,
        "error": None,
    }
    if SESSION is None:
        payload["error"] = "HTTP client unavailable"
    else:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/commits/{GITHUB_BRANCH}"
            response = SESSION.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    **({"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}),
                },
                timeout=10,
            )
            if response.status_code != 200:
                payload["error"] = f"GitHub HTTP {response.status_code}"
            else:
                remote = response.json()
                remote_commit = str(remote.get("sha") or "")
                if not re.fullmatch(r"[0-9a-f]{40}", remote_commit):
                    payload["error"] = "GitHub returned an invalid commit"
                else:
                    payload["ok"] = True
                    payload["remote_commit"] = remote_commit
                    payload["update_available"] = bool(current_commit and current_commit != remote_commit)
                    payload["remote_url"] = remote.get("html_url")
        except (requests.RequestException, ValueError, TypeError, KeyError):
            payload["error"] = "GitHub update check failed"

    if (
        not payload["ok"]
        and isinstance(cached, dict)
        and cached.get("ok")
    ):
        stale_payload = dict(cached)
        stale_payload["cache_age_sec"] = max(
            0, int(now_mono - cached_at)
        )
        stale_payload["stale"] = True
        stale_payload["error"] = payload["error"]
        with _GITHUB_UPDATE_CACHE_LOCK:
            _GITHUB_UPDATE_CACHE["attempt_ts"] = now_mono
            _GITHUB_UPDATE_CACHE["last_error"] = payload["error"]
        return stale_payload

    with _GITHUB_UPDATE_CACHE_LOCK:
        _GITHUB_UPDATE_CACHE["ts"] = now_mono
        _GITHUB_UPDATE_CACHE["attempt_ts"] = now_mono
        _GITHUB_UPDATE_CACHE["last_error"] = payload["error"]
        _GITHUB_UPDATE_CACHE["payload"] = payload
    return dict(payload)


@app.get("/api/update/check")
def update_check():
    return JSONResponse(_github_update_snapshot())


@app.get("/api/health")
def health():
    """Return sanitized host and trading health without exposing credentials."""
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
                    "watchdog": _systemd_service_snapshot("pi-watchdog-v3.timer"),
                },
                "heartbeat": _runtime_heartbeat_snapshot(),
                "ntp": _ntp_snapshot(),
                "binance": _binance_latency_snapshot(),
                "usb_backup": _usb_snapshot(),
                "backup": _backup_snapshot(),
                "user_stream": _user_stream_snapshot(
                    _load_ai_runtime_status()
                ),
            }
            _OPS_CACHE["ts"] = now_mono
            _OPS_CACHE["payload"] = ops
    network_probe_ok = network_ok()
    effective_network_ok = network_probe_ok or bool((ops.get("binance") or {}).get("ok"))
    return JSONResponse({
        "product": {"name": PRODUCT_NAME, "version": __version__},
        "changelog_url": "/CHANGELOG.md",
        "time": now_str(),
        "kernel": platform.release() or None,
        "host": _host_snapshot(),
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
        # DNS/53 may be blocked on a local network; a successful Binance probe
        # is the more relevant signal for the trading channel.
        "network_ok": effective_network_ok,
        "network_probe_ok": network_probe_ok,
        "operations": ops,
        "deployment": read_deployment_status(),
    })


@app.get("/api/account/balances")
def account_balances():
    """Handle account balances."""
    try:
        return JSONResponse(account_balances_snapshot())
    except _DATA_SOURCE_ERRORS as exc:
        print(f"[DASHBOARD] ACCOUNT_BALANCE_FAILED type={type(exc).__name__}", flush=True)
        fallback = _stale_binance_snapshot(
            _BALANCE_CACHE,
            _BALANCE_CACHE_LOCK,
            "ACCOUNT_BALANCE_STALE",
        )
        if fallback is not None:
            return JSONResponse(
                fallback,
                headers={"Warning": '110 - "stale Binance balance snapshot"'},
            )
        return JSONResponse({"ok": False, "error": "ACCOUNT_BALANCE_FAILED"}, status_code=503)


@app.get("/api/account/open-orders")
def account_open_orders():
    """Handle account open orders."""
    try:
        return JSONResponse(account_open_orders_snapshot())
    except _DATA_SOURCE_ERRORS as exc:
        print(f"[DASHBOARD] OPEN_ORDERS_FAILED type={type(exc).__name__}", flush=True)
        fallback = _stale_binance_snapshot(
            _OPEN_ORDERS_CACHE,
            _OPEN_ORDERS_CACHE_LOCK,
            "OPEN_ORDERS_STALE",
        )
        if fallback is not None:
            return JSONResponse(
                fallback,
                headers={"Warning": '110 - "stale Binance open-orders snapshot"'},
            )
        return JSONResponse({"ok": False, "error": "OPEN_ORDERS_FAILED"}, status_code=503)

@app.get("/api/history")
def history(hours: int = 24, points: int = 288):
    hours = max(1, min(hours, 168))
    payload = load_history_payload(
        HIST_FILE,
        cutoff_epoch=int(time.time()) - hours * 3600,
        points=points,
        timezone=APP_TZ,
    )
    epochs = payload.pop("_epochs")
    connection = None
    try:
        connection, _ = _open_db()
        payload["trading_volume_24h_usdt"] = rolling_trade_volume_24h_usdt(
            connection, epochs
        )
        payload["trading_volume_24h_status"] = "exact"
    except (OSError, sqlite3.Error, RuntimeError, ValueError):
        payload["trading_volume_24h_usdt"] = [None] * len(epochs)
        payload["trading_volume_24h_status"] = "unavailable"
    finally:
        if connection is not None:
            connection.close()
    return JSONResponse(payload)


def _ai_cache_get(key: str) -> Optional[Dict]:
    now = time.monotonic()
    with _AI_SUMMARY_CACHE_LOCK:
        entry = _AI_SUMMARY_CACHE.get(key)
        if not entry or now - float(entry["cached_at"]) > DASHBOARD_AI_AGGREGATE_CACHE_SEC:
            _AI_SUMMARY_CACHE.pop(key, None)
            return None
        return dict(entry["payload"])


def _ai_cache_put(key: str, payload: Dict) -> Dict:
    with _AI_SUMMARY_CACHE_LOCK:
        _AI_SUMMARY_CACHE[key] = {
            "cached_at": time.monotonic(),
            "payload": dict(payload),
        }
        # Runtime path changes are rare; this bound prevents abandoned paths
        # from accumulating after repeated configuration migrations.
        while len(_AI_SUMMARY_CACHE) > 16:
            oldest = min(
                _AI_SUMMARY_CACHE,
                key=lambda item: float(_AI_SUMMARY_CACHE[item]["cached_at"]),
            )
            _AI_SUMMARY_CACHE.pop(oldest, None)
    return payload


def _ai_usage_today(path: Path, *, now: datetime | None = None) -> Dict:
    # Limits and DEGRADED state must match AI policy and reset on UTC boundaries.
    # APP_TZ is used only for local-time presentation.
    now = now or datetime.now(tz=timezone.utc)
    now = now.astimezone(timezone.utc)
    today = now.date()
    cache_key = f"usage:{path}:{today.isoformat()}"
    cached = _ai_cache_get(cache_key)
    if cached is not None:
        return cached
    requests_count = tokens = errors = recent_errors = 0
    cost = Decimal("0")
    last_error_at = None
    if not path.exists():
        return _ai_cache_put(cache_key, {
            "requests": 0,
            "tokens": 0,
            "cost_usd": "0",
            "errors": 0,
            "recent_errors": 0,
            "last_error_at": None,
            "error_window_sec": AI_ERROR_DEGRADED_WINDOW_SEC,
        })
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
    return _ai_cache_put(cache_key, {
        "requests": requests_count,
        "tokens": tokens,
        "cost_usd": str(cost),
        "errors": errors,
        "recent_errors": recent_errors,
        "last_error_at": last_error_at,
        "error_window_sec": AI_ERROR_DEGRADED_WINDOW_SEC,
    })


def _ai_database_aggregates(
    connection: sqlite3.Connection,
    *,
    db_path: Path,
    evaluation_expression: str,
    tables: set[str],
) -> Dict:
    """Compute growing AI counters in SQL and cache the bounded result."""
    cache_key = f"database:{db_path}"
    cached = _ai_cache_get(cache_key)
    if cached is not None:
        return cached

    stats = {
        "documents": 0,
        "virtual_documents": 0,
        "archived_virtual_documents": 0,
        "virtual_policy": "archived_not_retrievable",
        "retrievals": 0,
        "unresolved_fills": 0,
        "unresolved_attribution_fills": 0,
        "unresolved_inventory_fills": 0,
        "reviewed_unattributable_fills": 0,
        "closed_decisions": 0,
        "realized_net_pnl_quote": 0.0,
    }
    safe_evaluation = (
        f"CASE WHEN json_valid({evaluation_expression}) "
        f"THEN {evaluation_expression} ELSE '{{}}' END"
    )
    realized = connection.execute(
        f"""
        SELECT
          COALESCE(SUM(CASE
            WHEN json_extract({safe_evaluation}, '$.realized_execution.closed') = 1
            THEN 1 ELSE 0 END), 0) AS closed_count,
          COALESCE(SUM(CASE
            WHEN json_extract({safe_evaluation}, '$.realized_execution.closed') = 1
            THEN CAST(COALESCE(
              json_extract({safe_evaluation}, '$.realized_execution.net_pnl_quote_text'),
              json_extract({safe_evaluation}, '$.realized_execution.net_pnl_quote'),
              0
            ) AS REAL)
            ELSE 0 END), 0) AS net_pnl
        FROM ai_decisions
        """
    ).fetchone()
    stats["closed_decisions"] = int(realized["closed_count"] or 0)
    stats["realized_net_pnl_quote"] = float(realized["net_pnl"] or 0)

    if "knowledge_documents" in tables:
        document_rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM knowledge_documents
            WHERE status IN ('validated', 'virtual_validated')
            GROUP BY status
            """
        ).fetchall()
        for row in document_rows:
            target = (
                "documents"
                if row["status"] == "validated"
                else "archived_virtual_documents"
            )
            stats[target] = int(row["count"])
    if "knowledge_retrievals" in tables:
        stats["retrievals"] = int(
            connection.execute("SELECT COUNT(*) FROM knowledge_retrievals").fetchone()[0]
        )
    if "ai_unresolved_fills" in tables:
        from ladder_dragon.ai.unresolved_fills import lifecycle_counts

        unresolved = lifecycle_counts(connection)
        stats["unresolved_fills"] = unresolved["pending"]
        stats["unresolved_attribution_fills"] = unresolved["attribution"]
        stats["unresolved_inventory_fills"] = unresolved["inventory"]
        stats["reviewed_unattributable_fills"] = unresolved[
            "reviewed_unattributable"
        ]
    return _ai_cache_put(cache_key, stats)


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
    """Handle ai status."""
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
        "documents": 0, "virtual_documents": 0,
        "archived_virtual_documents": 0,
        "virtual_policy": "archived_not_retrievable",
        "retrievals": 0,
        "unresolved_fills": 0,
        "unresolved_attribution_fills": 0,
        "unresolved_inventory_fills": 0,
        "reviewed_unattributable_fills": 0,
        "closed_decisions": 0,
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
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                knowledge_stats.update(
                    _ai_database_aggregates(
                        connection,
                        db_path=db_path,
                        evaluation_expression=expressions["evaluation_json"],
                        tables=tables,
                    )
                )
                if "knowledge_retrievals" in tables:
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
        except sqlite3.Error as exc:
            print(f"[DASHBOARD] AI_DB_READ_FAILED type={type(exc).__name__}", flush=True)
            return JSONResponse({"ok": False, "error": "AI_DB_READ_FAILED"}, status_code=503)
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
    runtime_reason = runtime_degraded_reason(
        runtime, follow_bot_paths=DASHBOARD_FOLLOW_BOT_PATHS, stale=runtime_stale
    )
    degraded_reasons = []
    if budget_exhausted:
        degraded_reasons.append("daily_budget_exhausted")
    if usage.get("recent_errors", 0) >= AI_ERROR_DEGRADED_MIN:
        degraded_reasons.append("recent_ai_errors")
    if effective_mode == "APPLY":
        # A production-gate rejection in APPLY is an independent DEGRADED reason:
        # the model may respond, but its statistics do not yet permit strategy impact.
        for row in recent:
            if str(row.get("status", "")).upper() != "REJECTED":
                continue
            for reason in str(row.get("policy_reasons", "")).split(","):
                reason = reason.strip()
                if reason and f"policy:{reason}" not in degraded_reasons:
                    degraded_reasons.append(f"policy:{reason}")
    if runtime_reason:
        degraded_reasons.append(runtime_reason)
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
            "auth_backoff": runtime.get("auth_backoff"),
            "ip_guard": runtime.get("ip_guard"),
            "recovery": runtime.get("recovery"),
            "provider": runtime_ai.get("provider"),
            "model": runtime_ai.get("model"),
            # Publish only numeric policy limits. The dashboard must not read
            # the bot's private .env or maintain a second configuration copy.
            "budgets": {
                "max_requests_per_day": request_limit,
                "max_tokens_per_day": token_limit,
                "max_cost_usd_per_day": str(cost_limit),
            },
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
    """Handle ai control snapshot."""
    runtime = _load_ai_runtime_status()
    runtime_ai = runtime.get("ai", {}) if isinstance(runtime.get("ai"), dict) else {}
    configured = bool(runtime_ai.get("enabled"))
    configured_mode = str(runtime_ai.get("configured_mode") or AI_MODE).upper()
    control_error = None
    try:
        control = read_ai_control(AI_CONTROL_FILE)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        control = None
        print(f"[DASHBOARD] AI_CONTROL_READ_FAILED type={type(exc).__name__}", flush=True)
        control_error = "AI_CONTROL_READ_FAILED"
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
    """Handle ai control."""
    snapshot = _ai_control_snapshot()
    if snapshot["control_error"]:
        return JSONResponse(
            {"ok": False, "error": "AI control file is invalid", **snapshot},
            status_code=503,
        )
    return {"ok": True, **snapshot}


@app.post("/api/ai/control")
async def set_ai_control(request: Request):
    """Handle set ai control."""
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
        print(f"[DASHBOARD] AI_CONTROL_WRITE_FAILED type={type(exc).__name__}", flush=True)
        return JSONResponse({"ok": False, "error": "AI_CONTROL_WRITE_FAILED"}, status_code=503)
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
    """Handle trades symbols."""
    hours = int(hours)
    cutoff = int(time.time()) - max(0, hours) * 3600 if hours > 0 else 0
    try:
        con, _ = _open_db()
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"[DASHBOARD] DB_OPEN_FAILED type={type(exc).__name__}", flush=True)
        return _database_unavailable_response()
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
        except sqlite3.Error: pass

# ---- trades summary & recent ------------------------------------------------------

@app.get("/api/trades/summary")
def trades_summary(hours: int = 24, symbols: str = ""):
    """
    Return trading totals and three deliberately separate accounting measures.

    ``cashflow_pnl_usdt`` is sells minus buys minus fees. ``net_pnl_usdt`` and
    ``realized_pnl_usdt`` are identical FIFO realized trading PnL after BUY and
    SELL fees. ``portfolio_change_usdt`` and ``equity_pnl_usdt`` are the
    mark-to-market portfolio value change and must not be presented as bot
    earnings. Equity uses Binance balances and historical/current prices, with
    an explicit approximation fallback.
    """
    hours = max(1, min(int(hours), 168))
    end_s = int(time.time())
    cutoff_s = end_s - hours * 3600
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None

    try:
        con, path = _open_db()
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"[DASHBOARD] DB_OPEN_FAILED type={type(exc).__name__}", flush=True)
        return _database_unavailable_response()

    fee_pct = _fee_pct_default()
    try:
        rows = _load_trades(con, syms)
        stats = _fifo_realized_pnl(rows, cutoff_s, fee_pct, end_s=end_s)
        eq = equity_pnl_usdt(cutoff_s, rows, fee_pct, syms)

        equity_then = eq.get("equity_then_usdt")
        equity_pnl  = eq.get("equity_pnl_usdt")
        equity_pct  = eq.get("equity_pct")
        if equity_pct is None and (equity_then not in (None, 0)) and (equity_pnl is not None) and abs(equity_then) >= 10.0:
            try:
                equity_pct = round((equity_pnl / equity_then) * 100.0, 2)
            except (ArithmeticError, TypeError, ValueError):
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
            "net_pnl_usdt": stats["realized_pnl_usdt"],
            "realized_pnl_method": (
                "unavailable-incomplete-fifo-history"
                if stats.get("realized_pnl_status", "exact") != "exact"
                else "fifo-net-fees"
            ),
            "realized_pnl_status": stats.get("realized_pnl_status", "exact"),
            "realized_pnl_excluded_symbols": stats.get(
                "realized_pnl_excluded_symbols", []
            ),
            "portfolio_change_usdt": eq["equity_pnl_usdt"],
            "equity_pnl_usdt": eq["equity_pnl_usdt"],
            "equity_now_usdt": eq.get("equity_now_usdt"),
            "equity_now_usdt_approx": eq.get("equity_now_usdt_approx"),
            "equity_then_usdt": equity_then,
            "equity_pct": equity_pct,
            "equity_method": eq.get("method"),
            "equity_assets": eq.get("equity_assets"),
        })
    finally:
        try: con.close()
        except sqlite3.Error: pass

@app.get("/api/trades/recent")
def trades_recent(limit: int = 20, symbols: str = ""):
    limit = max(1, min(int(limit), 5000))
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    try:
        con, path = _open_db()
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"[DASHBOARD] DB_OPEN_FAILED type={type(exc).__name__}", flush=True)
        return _database_unavailable_response()
    try:
        sym_filter = ""
        args: List = []
        if syms:
            qs = ",".join("?" for _ in syms)
            sym_filter = f" AND symbol IN ({qs})"
            args.extend(syms)
        sql = f"""
        SELECT symbol, side, price_text AS price, gross_qty_text AS qty,
               COALESCE(commission_quote_text, '0') AS fee_quote,
               CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
        FROM trades_exact
        WHERE 1=1 {sym_filter}
        ORDER BY ts_s DESC
        LIMIT ?
        """
        args.append(limit)
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
        for r in rows:
            r["price"] = float(Decimal(str(r["price"])))
            r["qty"] = float(Decimal(str(r["qty"])))
            r["fee_quote"] = float(Decimal(str(r["fee_quote"])))
            r["time"] = datetime.fromtimestamp(int(r["ts_s"]), APP_TZ).strftime("%Y-%m-%d %H:%M:%S")
        return JSONResponse({"ok": True, "rows": rows})
    finally:
        try: con.close()
        except sqlite3.Error: pass

# ---- Filled orders (24h) for dashboard -------------------------------------------

def _select_filled_orders(
    hours: int,
    syms: Optional[List[str]],
    limit: int,
    offset: int = 0,
) -> List[Dict]:
    """Handle select filled orders."""
    hours = max(1, min(int(hours), 168))
    limit = max(1, min(int(limit), 500))
    offset = max(0, min(int(offset), 50000))
    cutoff_s = int(time.time()) - hours * 3600

    con, _ = _open_db()

    try:
        sym_filter = ""
        args: List = []
        if syms:
            qs = ",".join("?" for _ in syms)
            sym_filter = f" AND symbol IN ({qs})"
            args.extend(syms)

        sql = f"""
        SELECT
          symbol, side, price_text AS price, gross_qty_text AS qty,
          COALESCE(commission_quote_text, '0') AS fee_quote,
          CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
        FROM trades_exact
        WHERE 1=1 {sym_filter}
          AND (CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END) >= ?
        ORDER BY ts_s DESC
        LIMIT ? OFFSET ?
        """
        args.extend([cutoff_s, limit, offset])
        rows = con.execute(sql, args).fetchall()

        fee_pct = _fee_pct_default()
        out: List[Dict] = []
        for r in rows:
            price = float(r["price"])
            qty = float(r["qty"])
            fee_q = float(r["fee_quote"])
            # If fee_quote is zero (BNB), estimate the fee in USDT by percentage.
            fee_usdt = fee_q if fee_q > 0 else (price * qty * fee_pct)
            out.append({
                "time": int(r["ts_s"]) * 1000,
                "symbol": r["symbol"],
                "side": str(r["side"]).upper(),
                "price": round(price, 8),
                "qty": round(qty, 8),
                "quoteQty": round(price * qty, 8),
                "commission": round(fee_usdt, 8),
                "commissionAsset": "USDT"
            })
        return out
    finally:
        try:
            if con: con.close()
        except sqlite3.Error:
            pass

@app.get("/api/trades/filled")
def api_trades_filled(
    hours: int = 24, symbols: str = "", limit: int = 300, offset: int = 0
):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    items = _select_filled_orders(hours, syms, limit, offset)
    return JSONResponse(items)

@app.get("/api/orders/filled")
def api_orders_filled(
    hours: int = 24, symbols: str = "", limit: int = 300, offset: int = 0
):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    items = _select_filled_orders(hours, syms, limit, offset)
    return JSONResponse(items)

@app.get("/api/fills")
def api_fills(
    hours: int = 24, symbols: str = "", limit: int = 300, offset: int = 0
):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    items = _select_filled_orders(hours, syms, limit, offset)
    return JSONResponse(items)
