# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: prove Mainnet User Data Stream event-to-REST behavior safely.
"""Run one bounded Mainnet LIMIT_MAKER event drill under persistent HALT."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping

import requests
from dotenv import load_dotenv

from ladder_dragon.execution.exchange_math import decimal, format_step, round_step
from ladder_dragon.execution.order_identity import client_order_id
from ladder_dragon.execution.order_recovery import OrderJournal, read_order_journal_telemetry
from ladder_dragon.execution.time_safety import assess_exchange_clock
from ladder_dragon.risk.risk_manager import RiskLimits, create_manual_halt
from ladder_dragon.verification.live.mainnet_canary import (
    ALLOWED_SYMBOL,
    HARD_MAX_NOTIONAL_USDT,
    MAINNET_BASE,
    MainnetCanaryClient,
    exclusive_lock,
    require_release_not_already_passed,
    resolve_project_path,
)
from ladder_dragon.verification.live.testnet_smoke import (
    balance_amount,
    build_non_filling_limit_buy,
    symbol_assets,
    symbol_rules,
)
from product_version import __version__


DEFAULT_NOTIONAL_USDT = Decimal("6")
STATE_PATH = Path(
    "/var/lib/ladder-dragon/user-stream/user_stream_SOLUSDT.json"
)
RUNTIME_PATH = Path("/run/mybot/ai_status.json")
CONFIRMATIONS = {
    "BOT_LIVE_CONFIRMED": "YES",
    "BOT_MAINNET_USER_STREAM_DRILL_CONFIRMED": "YES",
    "BOT_MAINNET_USER_STREAM_DRILL_CLEANUP_CONFIRMED": "YES",
}
DRILL_ERRORS = (
    ArithmeticError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    requests.RequestException,
)
TERMINAL = {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "FILLED", "REJECTED"}


def _read_object(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{description} is unavailable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{description} is not an object")
    return payload


def _require_confirmations(environ: Mapping[str, str]) -> None:
    missing = sorted(
        name for name, expected in CONFIRMATIONS.items()
        if environ.get(name) != expected
    )
    if missing:
        raise RuntimeError(
            "Mainnet User Stream drill confirmation missing: "
            + ", ".join(missing)
        )


def _require_halted_shadow(runtime_path: Path) -> None:
    runtime = _read_object(runtime_path, "runtime status")
    risk = runtime.get("risk")
    ai = runtime.get("ai")
    if (
        runtime.get("execution_mode") != "LIVE"
        or runtime.get("venue") != "mainnet"
        or not isinstance(risk, dict)
        or risk.get("halted") is not True
        or risk.get("buy_blocked") is not True
        or not isinstance(ai, dict)
        or ai.get("mode") != "SHADOW"
    ):
        raise RuntimeError(
            "Mainnet User Stream drill requires LIVE SHADOW with BUY halted"
        )


def _require_observer(state_path: Path) -> dict[str, Any]:
    state = _read_object(state_path, "User Data Stream state")
    try:
        stale_sec = max(Decimal("0"), decimal(time.time()) - decimal(state_path.stat().st_mtime))
    except (OSError, ArithmeticError, TypeError, ValueError) as exc:
        raise RuntimeError("User Data Stream state age is unavailable") from exc
    if str(state.get("state") or "").lower() != "connected":
        raise RuntimeError("User Data Stream observer is not connected")
    if stale_sec > Decimal("180"):
        raise RuntimeError("User Data Stream state is stale")
    return state


def _query_order(client: Any, symbol: str, order_client_id: str) -> dict[str, Any]:
    payload = client.signed(
        "GET",
        "/api/v3/order",
        {"symbol": symbol, "origClientOrderId": order_client_id},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Mainnet drill order query returned invalid data")
    return payload


def _submit_order(
    client: Any,
    journal: OrderJournal,
    params: dict[str, str],
    *,
    purpose: str,
    parent_client_order_id: str | None = None,
) -> dict[str, Any]:
    order_client_id = params["newClientOrderId"]
    journal.prepare(
        client_order_id=order_client_id,
        parent_client_order_id=parent_client_order_id,
        symbol=params["symbol"],
        side=params["side"],
        purpose=purpose,
        order_type=params["type"],
        quantity=params["quantity"],
        price=params.get("price") or "MARKET",
    )
    try:
        payload = client.signed("POST", "/api/v3/order", params)
    except requests.RequestException as exc:
        journal.mark_unknown(order_client_id, exc)
        payload = _query_order(client, params["symbol"], order_client_id)
    if not isinstance(payload, dict):
        raise RuntimeError("Mainnet drill order response is invalid")
    payload.setdefault("clientOrderId", order_client_id)
    journal.record_exchange_order(order_client_id, payload)
    return payload


def _cancel_order(
    client: Any,
    journal: OrderJournal,
    *,
    symbol: str,
    order_client_id: str,
) -> dict[str, Any]:
    latest: dict[str, Any] | None = None
    for _attempt in range(3):
        latest = _query_order(client, symbol, order_client_id)
        if str(latest.get("status") or "").upper() in TERMINAL:
            break
        try:
            latest = client.signed(
                "DELETE",
                "/api/v3/order",
                {"symbol": symbol, "origClientOrderId": order_client_id},
            )
        except requests.RequestException:
            latest = _query_order(client, symbol, order_client_id)
        if str(latest.get("status") or "").upper() in TERMINAL:
            break
        time.sleep(0.2)
    if not isinstance(latest, dict):
        raise RuntimeError("Mainnet drill cancellation returned invalid data")
    state = journal.record_exchange_order(order_client_id, latest)
    if str(latest.get("status") or "").upper() not in TERMINAL:
        journal.mark_unknown(order_client_id, "cancellation is unconfirmed")
        raise RuntimeError("Mainnet drill cancellation is unconfirmed")
    if state.state == "UNKNOWN":
        raise RuntimeError("Mainnet drill terminal state is unknown")
    return latest


def _wait_for_stream_evidence(
    state_path: Path,
    *,
    order_events_before: int,
    event_rest_before: int,
    timeout_sec: Decimal = Decimal("30"),
) -> dict[str, Any]:
    deadline = Decimal(str(time.monotonic())) + timeout_sec
    while Decimal(str(time.monotonic())) < deadline:
        state = _require_observer(state_path)
        if (
            int(state.get("order_events") or 0) > order_events_before
            and int(state.get("event_woken_rest_reconciliations") or 0)
            > event_rest_before
        ):
            return state
        time.sleep(0.1)
    raise RuntimeError(
        "Mainnet order event did not produce authoritative REST evidence"
    )


def _flatten_unexpected_fill(
    client: Any,
    journal: OrderJournal,
    *,
    symbol: str,
    base_asset: str,
    initial_base_total: Decimal,
    rules: dict[str, Decimal],
    parent_client_order_id: str,
) -> None:
    account = client.signed("GET", "/api/v3/account")
    current_total = balance_amount(account, base_asset) + balance_amount(
        account, base_asset, "locked"
    )
    acquired = max(Decimal("0"), current_total - initial_base_total)
    quantity = round_step(acquired, rules["step"], "floor")
    ticker = client.public_get("/api/v3/ticker/price", {"symbol": symbol})
    if quantity < rules["min_qty"]:
        if acquired > rules["step"]:
            raise RuntimeError("unexpected fill is below cleanup minimum quantity")
        return
    if quantity * decimal(ticker["price"]) < rules["min_notional"]:
        raise RuntimeError("unexpected fill is below cleanup minimum notional")
    quantity_text = format_step(quantity, rules["step"])
    cleanup_id = client_order_id(
        symbol,
        "SELL",
        "mainnet_stream_drill_cleanup",
        "MARKET",
        quantity_text,
        bucket_seconds=1,
    )
    payload = _submit_order(
        client,
        journal,
        {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": quantity_text,
            "newOrderRespType": "FULL",
            "newClientOrderId": cleanup_id,
        },
        purpose="mainnet_stream_drill_cleanup",
        parent_client_order_id=parent_client_order_id,
    )
    if str(payload.get("status") or "").upper() != "FILLED":
        payload = _query_order(client, symbol, cleanup_id)
        journal.record_exchange_order(cleanup_id, payload)
    if str(payload.get("status") or "").upper() != "FILLED":
        raise RuntimeError("unexpected fill cleanup is not FILLED")


def run_drill(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] = os.environ,
    client: Any | None = None,
) -> dict[str, Any]:
    """Place and cancel one bounded non-taking order for stream evidence."""
    _require_confirmations(environ)
    symbol = str(args.symbol).strip().upper()
    if symbol != ALLOWED_SYMBOL:
        raise RuntimeError(f"Mainnet User Stream drill is restricted to {ALLOWED_SYMBOL}")
    requested = decimal(args.notional_usdt)
    if (
        not requested.is_finite()
        or requested <= 0
        or requested > HARD_MAX_NOTIONAL_USDT
    ):
        raise RuntimeError("Mainnet drill notional must be in (0, 10] USDT")
    runtime_path = Path(args.runtime)
    state_path = Path(args.state)
    _require_halted_shadow(runtime_path)
    observer_before = _require_observer(state_path)
    limits = RiskLimits.from_mapping(environ)
    if limits.reserve_usdt <= 0:
        raise RuntimeError("RISK_RESERVE_USDT must be greater than zero")
    if not limits.halt_file.is_file():
        raise RuntimeError("persistent circuit HALT is unavailable")
    report_path = resolve_project_path(args.report)
    require_release_not_already_passed(report_path)
    journal_path = resolve_project_path(args.journal)
    production_journal_path = resolve_project_path(args.production_journal)
    if journal_path == production_journal_path:
        raise RuntimeError("drill and production journals must be separate files")
    production = read_order_journal_telemetry(production_journal_path)
    if not production.get("available") or int(production.get("pending") or 0):
        raise RuntimeError("production journal is unavailable or nonterminal")
    if client is None:
        api_key = environ.get("BINANCE_API_KEY", "")
        api_secret = environ.get("BINANCE_API_SECRET", "")
        if not api_key or not api_secret:
            raise RuntimeError("BINANCE_API_KEY/SECRET are required")
        client = MainnetCanaryClient(MAINNET_BASE, api_key, api_secret)

    started_ms = int(time.time() * 1000)
    server = client.public_get("/api/v3/time")
    finished_ms = int(time.time() * 1000)
    assess_exchange_clock(
        server_time_ms=int(server["serverTime"]),
        request_started_ms=started_ms,
        response_finished_ms=finished_ms,
        max_offset_ms=1000,
        max_round_trip_ms=5000,
    ).require_safe()
    exchange_info = client.public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    rules = symbol_rules(exchange_info)
    base_asset, quote_asset = symbol_assets(exchange_info)
    if (base_asset, quote_asset) != ("SOL", "USDT"):
        raise RuntimeError("Mainnet drill asset mapping is not SOL/USDT")
    account_before = client.signed("GET", "/api/v3/account")
    if account_before.get("canTrade") is not True:
        raise RuntimeError("Binance account is not allowed to trade")
    if balance_amount(account_before, quote_asset) - requested < limits.reserve_usdt:
        raise RuntimeError("Mainnet drill would violate the USDT reserve")
    open_orders = client.signed("GET", "/api/v3/openOrders", {"symbol": symbol})
    if open_orders:
        raise RuntimeError("Mainnet drill requires no open SOLUSDT orders")
    ticker = client.public_get("/api/v3/ticker/price", {"symbol": symbol})
    params = build_non_filling_limit_buy(
        symbol=symbol,
        market_price=ticker["price"],
        rules=rules,
        notional_usdt=requested,
    )
    params["newClientOrderId"] = client_order_id(
        symbol,
        "BUY",
        "mainnet_stream_drill",
        params["price"],
        params["quantity"],
        bucket_seconds=1,
    )
    actual_notional = decimal(params["price"]) * decimal(params["quantity"])
    if actual_notional > HARD_MAX_NOTIONAL_USDT:
        raise RuntimeError("normalized drill order exceeds the hard 10 USDT ceiling")
    client.signed("POST", "/api/v3/order/test", params)
    journal = OrderJournal(journal_path, venue="mainnet-user-stream-drill")
    if journal.nonterminal_orders(symbol):
        raise RuntimeError("Mainnet drill journal contains nonterminal intents")
    initial_base_total = balance_amount(account_before, base_asset) + balance_amount(
        account_before, base_asset, "locked"
    )
    created: dict[str, Any] | None = None
    final: dict[str, Any] | None = None
    mutation_started = False
    primary_error: BaseException | None = None
    try:
        mutation_started = True
        created = _submit_order(
            client,
            journal,
            params,
            purpose="mainnet_stream_drill",
        )
        final = _cancel_order(
            client,
            journal,
            symbol=symbol,
            order_client_id=params["newClientOrderId"],
        )
        _flatten_unexpected_fill(
            client,
            journal,
            symbol=symbol,
            base_asset=base_asset,
            initial_base_total=initial_base_total,
            rules=rules,
            parent_client_order_id=params["newClientOrderId"],
        )
        if decimal(final.get("executedQty") or "0") > 0:
            journal.mark_closed(params["newClientOrderId"])
            raise RuntimeError("Mainnet drill order unexpectedly executed")
        observer_after = _wait_for_stream_evidence(
            state_path,
            order_events_before=int(observer_before.get("order_events") or 0),
            event_rest_before=int(
                observer_before.get("event_woken_rest_reconciliations") or 0
            ),
        )
        if client.signed("GET", "/api/v3/openOrders", {"symbol": symbol}):
            raise RuntimeError("Mainnet drill cleanup left an open order")
        report = {
            "schema_version": 1,
            "product_version": __version__,
            "venue": "mainnet",
            "mode": "user-stream-event-drill",
            "symbol": symbol,
            "status": "passed",
            "notional_limit_usdt": str(actual_notional),
            "order_status": str(final.get("status") or "UNKNOWN"),
            "executed_qty": str(final.get("executedQty") or "0"),
            "order_events_delta": int(observer_after.get("order_events") or 0)
            - int(observer_before.get("order_events") or 0),
            "event_rest_delta": int(
                observer_after.get("event_woken_rest_reconciliations") or 0
            ) - int(observer_before.get("event_woken_rest_reconciliations") or 0),
        }
        from ladder_dragon.verification.live.mainnet_canary import _append_report
        _append_report(report_path, report)
        return report
    except DRILL_ERRORS as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            if mutation_started and (
                final is None
                or str(final.get("status") or "").upper() not in TERMINAL
            ):
                _cancel_order(
                    client,
                    journal,
                    symbol=symbol,
                    order_client_id=params["newClientOrderId"],
                )
            if created is not None:
                _flatten_unexpected_fill(
                    client,
                    journal,
                    symbol=symbol,
                    base_asset=base_asset,
                    initial_base_total=initial_base_total,
                    rules=rules,
                    parent_client_order_id=params["newClientOrderId"],
                )
        except DRILL_ERRORS as exc:
            cleanup_error = exc
        if primary_error is not None or cleanup_error is not None:
            reason = "Mainnet User Stream drill failed closed"
            create_manual_halt(
                reason,
                limits=limits,
                metadata={"symbol": symbol, "purpose": "user-stream-drill"},
            )
            if primary_error is not None:
                if cleanup_error is not None:
                    raise primary_error from cleanup_error
                raise primary_error
            raise RuntimeError(reason) from cleanup_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded Mainnet User Data Stream event drill"
    )
    parser.add_argument("--symbol", default=ALLOWED_SYMBOL)
    parser.add_argument("--notional-usdt", type=Decimal, default=DEFAULT_NOTIONAL_USDT)
    parser.add_argument("--runtime", type=Path, default=RUNTIME_PATH)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument(
        "--journal", default="db/mainnet_user_stream_drill_order_intents.sqlite3"
    )
    parser.add_argument(
        "--production-journal",
        default=os.getenv("BOT_ORDER_JOURNAL", "db/order_intents.sqlite3"),
    )
    parser.add_argument("--report", default="logs/mainnet_user_stream_drill.ndjson")
    parser.add_argument("--lock-file", default=".runtime/mainnet-user-stream-drill.lock")
    return parser


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env")
    parser = build_parser()
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol.strip().upper()):
        parser.error("--symbol must be an uppercase Binance symbol")
    print(json.dumps({
        "venue": "mainnet",
        "mode": "user-stream-event-drill",
        "symbol": args.symbol.strip().upper(),
        "hard_max_notional_usdt": str(HARD_MAX_NOTIONAL_USDT),
        "cleanup": "mandatory",
        "requires_halt": True,
    }, sort_keys=True), flush=True)
    try:
        with exclusive_lock(args.lock_file):
            report = run_drill(args)
    except DRILL_ERRORS as exc:
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        }, sort_keys=True), file=sys.stderr, flush=True)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "run_drill"]
