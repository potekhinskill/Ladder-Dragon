#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run one bounded, self-cleaning Binance Spot Mainnet canary lifecycle.
"""Deterministic Mainnet BUY -> OCO -> journal reload -> cleanup canary.

This command is intentionally separate from the trading strategy. It refuses to
run while ``mybot`` or its watchdog timer is active, accepts only ``SOLUSDT``,
hard-caps quote exposure at 10 USDT, preserves the configured USDT reserve, and
requires two canary-specific confirmations in addition to the normal LIVE gate.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from bin.binance_testnet_smoke import (
    balance_amount,
    execute_buy_oco_lifecycle,
    symbol_assets,
    symbol_rules,
)
from ladder_dragon.execution.binance_transport import BinanceTransport
from ladder_dragon.execution.exchange_math import decimal
from ladder_dragon.execution.order_recovery import (
    OrderJournal,
    read_order_journal_telemetry,
)
from ladder_dragon.execution.time_safety import assess_exchange_clock
from ladder_dragon.risk.risk_manager import RiskLimits, create_manual_halt
from product_version import user_agent


MAINNET_BASE = "https://api.binance.com"
MAINNET_HOST = "api.binance.com"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SYMBOL = "SOLUSDT"
HARD_MAX_NOTIONAL_USDT = Decimal("10")
DEFAULT_NOTIONAL_USDT = Decimal("6")
SYSTEMCTL = "/usr/bin/systemctl"
REQUIRED_CONFIRMATIONS = {
    "BOT_LIVE_CONFIRMED": "YES",
    "BOT_MAINNET_CANARY_CONFIRMED": "YES",
    "BOT_MAINNET_CANARY_CLEANUP_CONFIRMED": "YES",
}


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def validate_mainnet_base(base_url: str) -> str:
    """Accept only the canonical Binance Spot Mainnet origin."""
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != MAINNET_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Mainnet canary requires https://api.binance.com")
    return MAINNET_BASE


class MainnetCanaryClient:
    """Small Binance client using the shared redacting/retrying transport."""

    def __init__(self, base_url: str, api_key: str, api_secret: str) -> None:
        self.base_url = validate_mainnet_base(base_url)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent("MainnetCanary")})
        self.transport = BinanceTransport(
            self.session,
            base_url=lambda: self.base_url,
            api_key=lambda: api_key,
            api_secret=lambda: api_secret,
            live=lambda: True,
            recv_window=lambda: 5000,
            logger=lambda message: print(message, flush=True),
        )

    def public_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.transport.public_get(path, params, timeout=15)

    def signed(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.transport.signed_request(method, path, params, timeout=15)


def require_confirmations(environ: Mapping[str, str]) -> None:
    missing = [
        name for name, expected in REQUIRED_CONFIRMATIONS.items()
        if environ.get(name) != expected
    ]
    if missing:
        raise RuntimeError(
            "Mainnet canary confirmation missing: " + ", ".join(sorted(missing))
        )


def require_services_stopped(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Refuse concurrent strategy or watchdog activity."""
    for unit in (
        "mybot.service",
        "pi-watchdog-v3.timer",
        "pi-watchdog-v3.service",
    ):
        result = runner(
            [SYSTEMCTL, "is-active", unit],
            text=True,
            capture_output=True,
            check=False,
        )
        state = (result.stdout or "").strip().lower()
        if state not in ("inactive", "failed", "unknown"):
            raise RuntimeError(f"refusing Mainnet canary while {unit} is {state or 'active'}")


@contextmanager
def exclusive_lock(path: str | Path) -> Iterator[None]:
    """Acquire a private lock without depending on a systemd RuntimeDirectory."""
    target = resolve_project_path(path)
    fd: int | None = None
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags, 0o600)
        os.fchmod(fd, 0o600)
    except OSError as exc:
        if fd is not None:
            os.close(fd)
        raise RuntimeError(
            f"cannot create private Mainnet canary lock: {type(exc).__name__}"
        ) from exc

    assert fd is not None
    with os.fdopen(fd, "a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another Mainnet canary process owns the lock") from exc
        except OSError as exc:
            raise RuntimeError(
                f"cannot acquire Mainnet canary lock: {type(exc).__name__}"
            ) from exc
        yield


def _append_report(path: str | Path, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(target, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n"
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _configured_reserve(environ: Mapping[str, str]) -> Decimal:
    raw = environ.get("RISK_RESERVE_USDT", "")
    try:
        reserve = decimal(raw)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise RuntimeError("RISK_RESERVE_USDT must be configured for Mainnet canary") from exc
    if reserve <= 0:
        raise RuntimeError("RISK_RESERVE_USDT must be greater than zero")
    return reserve


def _preflight(
    *,
    client: Any,
    symbol: str,
    notional_usdt: Decimal,
    reserve_usdt: Decimal,
    journal_path: str | Path,
    production_journal_path: str | Path,
    limits: RiskLimits,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Decimal],
    dict[str, Any],
]:
    if limits.halt_file.exists():
        raise RuntimeError(f"circuit halt exists: {limits.halt_file}")

    started_ms = int(time.time() * 1000)
    server = client.public_get("/api/v3/time")
    finished_ms = int(time.time() * 1000)
    clock = assess_exchange_clock(
        server_time_ms=int(server["serverTime"]),
        request_started_ms=started_ms,
        response_finished_ms=finished_ms,
        max_offset_ms=1000,
        max_round_trip_ms=5000,
    )
    clock.require_safe()

    exchange_info = client.public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    rules = symbol_rules(exchange_info)
    row = (exchange_info.get("symbols") or [{}])[0]
    if str(row.get("status") or "").upper() != "TRADING":
        raise RuntimeError(f"{symbol} is not TRADING")
    if row.get("isSpotTradingAllowed") is False:
        raise RuntimeError(f"Spot trading is disabled for {symbol}")
    filter_types = {
        item.get("filterType") for item in row.get("filters") or []
    }
    if not {"PERCENT_PRICE", "PERCENT_PRICE_BY_SIDE"} & filter_types:
        raise RuntimeError("Mainnet exchangeInfo has no percent-price filter")
    base_asset, quote_asset = symbol_assets(exchange_info)
    if (base_asset, quote_asset) != ("SOL", "USDT"):
        raise RuntimeError("Mainnet canary asset mapping is not SOL/USDT")

    minimum = rules["min_notional"] * Decimal("1.20")
    if notional_usdt < minimum:
        raise RuntimeError(f"canary notional must be at least {minimum} USDT")
    if notional_usdt > HARD_MAX_NOTIONAL_USDT:
        raise RuntimeError("canary notional exceeds the hard 10 USDT ceiling")

    account = client.signed("GET", "/api/v3/account")
    if account.get("canTrade") is not True:
        raise RuntimeError("Binance account is not allowed to trade")
    free_usdt = balance_amount(account, "USDT")
    if free_usdt - notional_usdt < reserve_usdt:
        raise RuntimeError(
            f"USDT reserve would be violated: free={free_usdt}, "
            f"notional={notional_usdt}, reserve={reserve_usdt}"
        )

    open_orders = client.signed("GET", "/api/v3/openOrders", {"symbol": symbol})
    if open_orders:
        raise RuntimeError(f"refusing canary with {len(open_orders)} open {symbol} orders")

    if Path(journal_path).resolve() == Path(production_journal_path).resolve():
        raise RuntimeError("canary and production journals must be separate files")
    production_journal = read_order_journal_telemetry(production_journal_path)
    if not production_journal.get("available"):
        raise RuntimeError(
            "production order journal is unavailable: "
            + str(production_journal.get("reason") or "unknown")
        )
    if int(production_journal.get("pending") or 0) != 0:
        raise RuntimeError("production order journal contains nonterminal intents")

    journal = OrderJournal(journal_path, venue="mainnet-canary")
    pending = journal.nonterminal_orders(symbol)
    if pending:
        raise RuntimeError(
            "unresolved prior Mainnet canary intents: "
            + ", ".join(item.client_order_id for item in pending)
        )
    return account, exchange_info, rules, {
        "clock_offset_ms": clock.offset_ms,
        "clock_round_trip_ms": clock.round_trip_ms,
        "clock_guaranteed_offset_ms": clock.guaranteed_offset_ms,
        "filters": {name: str(value) for name, value in rules.items()},
        "free_usdt_before": str(free_usdt),
        "open_orders_before": 0,
        "production_journal_pending": 0,
    }


def run_canary(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] = os.environ,
    client: Any | None = None,
    service_check: Callable[[], None] = require_services_stopped,
) -> dict[str, Any]:
    require_confirmations(environ)
    service_check()
    symbol = str(args.symbol).strip().upper()
    if symbol != ALLOWED_SYMBOL:
        raise RuntimeError(f"Mainnet canary is restricted to {ALLOWED_SYMBOL}")
    requested = decimal(args.notional_usdt)
    if requested <= 0 or requested > HARD_MAX_NOTIONAL_USDT:
        raise RuntimeError("Mainnet canary notional must be in (0, 10] USDT")
    reserve = _configured_reserve(environ)
    limits = RiskLimits.from_env()
    journal_path = resolve_project_path(args.journal)
    production_journal_path = resolve_project_path(args.production_journal)
    report_path = resolve_project_path(args.report)

    if client is None:
        api_key = environ.get("BINANCE_API_KEY", "")
        api_secret = environ.get("BINANCE_API_SECRET", "")
        if not api_key or not api_secret:
            raise RuntimeError("BINANCE_API_KEY/SECRET are required")
        client = MainnetCanaryClient(
            environ.get("BINANCE_API_BASE", MAINNET_BASE), api_key, api_secret
        )

    account_before, exchange_info, _rules, preflight = _preflight(
        client=client,
        symbol=symbol,
        notional_usdt=requested,
        reserve_usdt=reserve,
        journal_path=journal_path,
        production_journal_path=production_journal_path,
        limits=limits,
    )
    started_at = time.time()
    report: dict[str, Any] = {
        "schema_version": 1,
        "venue": "mainnet",
        "mode": "bounded-active-canary",
        "symbol": symbol,
        "notional_limit_usdt": str(requested),
        "reserve_usdt": str(reserve),
        "journal_path": str(journal_path),
        "preflight": preflight,
        "started_at_epoch": started_at,
        "status": "started",
    }
    try:
        lifecycle = execute_buy_oco_lifecycle(
            client=client,
            symbol=symbol,
            exchange_info=exchange_info,
            account_before=account_before,
            notional_usdt=requested,
            max_notional_usdt=HARD_MAX_NOTIONAL_USDT,
            reserve_usdt=reserve,
            take_profit_pct=args.take_profit_pct,
            stop_loss_pct=args.stop_loss_pct,
            stop_limit_offset_pct=args.stop_limit_offset_pct,
            journal_path=journal_path,
            restart_drill=True,
            venue="mainnet-canary",
            purpose_prefix="mainnet_canary",
            venue_label="Mainnet canary",
        )
        final_account = client.signed("GET", "/api/v3/account")
        final_open = client.signed(
            "GET", "/api/v3/openOrders", {"symbol": symbol}
        )
        if final_open:
            raise RuntimeError("Mainnet canary cleanup left open SOLUSDT orders")
        quote_delta = balance_amount(final_account, "USDT") - balance_amount(
            account_before, "USDT"
        )
        report.update(lifecycle)
        report.update(
            {
                "canary_id": lifecycle["buy_client_order_id"],
                "status": "passed",
                "quote_balance_delta_usdt": str(quote_delta),
                "open_orders_after": 0,
                "duration_sec": str(Decimal(str(time.time() - started_at)).quantize(Decimal("0.001"))),
            }
        )
        _append_report(report_path, report)
        return report
    except Exception as exc:
        # This is the post-mutation safety boundary: any unexpected failure
        # must persist a halt rather than allowing the normal bot to restart.
        reason = f"Mainnet canary failed closed: {type(exc).__name__}: {exc}"
        halt_path = create_manual_halt(
            reason,
            limits=limits,
            metadata={"symbol": symbol, "purpose": "mainnet-canary"},
        )
        report.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "halt_file": str(halt_path),
                "duration_sec": str(Decimal(str(time.time() - started_at)).quantize(Decimal("0.001"))),
            }
        )
        _append_report(report_path, report)
        raise RuntimeError(reason) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded fail-closed Binance Spot Mainnet canary"
    )
    parser.add_argument("--symbol", default=ALLOWED_SYMBOL)
    parser.add_argument(
        "--notional-usdt", type=Decimal, default=DEFAULT_NOTIONAL_USDT
    )
    parser.add_argument("--take-profit-pct", type=Decimal, default=Decimal("0.02"))
    parser.add_argument("--stop-loss-pct", type=Decimal, default=Decimal("0.02"))
    parser.add_argument(
        "--stop-limit-offset-pct", type=Decimal, default=Decimal("0.002")
    )
    parser.add_argument(
        "--journal",
        default="db/mainnet_canary_order_intents.sqlite3",
    )
    parser.add_argument(
        "--production-journal",
        default=os.getenv("BOT_ORDER_JOURNAL", "db/order_intents.sqlite3"),
    )
    parser.add_argument(
        "--report",
        default="logs/mainnet_canary.ndjson",
    )
    parser.add_argument(
        "--lock-file",
        default=".runtime/mainnet-canary.lock",
    )
    return parser


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = build_parser()
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol.strip().upper()):
        parser.error("--symbol must be an uppercase Binance symbol")
    if not Decimal("0") < args.take_profit_pct < Decimal("0.25"):
        parser.error("--take-profit-pct must be between 0 and 0.25")
    if not Decimal("0") < args.stop_loss_pct < Decimal("0.25"):
        parser.error("--stop-loss-pct must be between 0 and 0.25")
    if not Decimal("0") < args.stop_limit_offset_pct < args.stop_loss_pct:
        parser.error("--stop-limit-offset-pct must be positive and below stop loss")

    print(
        json.dumps(
            {
                "venue": "mainnet",
                "symbol": args.symbol.strip().upper(),
                "notional_usdt": str(args.notional_usdt),
                "hard_max_notional_usdt": str(HARD_MAX_NOTIONAL_USDT),
                "cleanup": "mandatory",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        with exclusive_lock(args.lock_file):
            result = run_canary(args)
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
