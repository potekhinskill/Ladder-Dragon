# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect one bounded Mainnet LIMIT_MAKER fill for replay validation.
"""Run one fail-closed Mainnet LIMIT_MAKER validation drill under HALT."""

from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping

import requests
from dotenv import load_dotenv

from ladder_dragon.execution.exchange_math import (
    decimal,
    format_step,
    normalized_order_values,
    round_step,
)
from ladder_dragon.execution.execution_latency import (
    append_execution_latency_sample,
)
from ladder_dragon.execution.executor_stats import commission_quote_value
from ladder_dragon.execution.order_identity import client_order_id
from ladder_dragon.execution.order_recovery import (
    OrderJournal,
    read_order_journal_telemetry,
)
from ladder_dragon.execution.user_stream import OrderStreamSignal
from ladder_dragon.execution.time_safety import assess_exchange_clock
from ladder_dragon.risk.risk_manager import RiskLimits, create_manual_halt
from ladder_dragon.strategy.expectancy_controls import (
    authoritative_commission_schedule,
)
from ladder_dragon.verification.live import mainnet_user_stream_drill as stream_drill
from ladder_dragon.verification.live.mainnet_canary import (
    ALLOWED_SYMBOL,
    MAINNET_BASE,
    MainnetCanaryClient,
    _append_report,
    exclusive_lock,
    resolve_project_path,
)
from ladder_dragon.verification.live.testnet_smoke import (
    balance_amount,
    symbol_assets,
    symbol_rules,
)
from ladder_dragon.verification.live.validation_archive import (
    ContinuousDepthArchive,
)
from ladder_dragon.verification.live.validation_batch import (
    reserve_validation_attempt,
)
from product_version import __version__


HARD_MAX_NOTIONAL_USDT = Decimal("6")
HARD_MAX_COMMISSION_USDT = Decimal("0.03")
DEFAULT_WAIT_SEC = Decimal("90")
CONFIRMATIONS = {
    "BOT_LIVE_CONFIRMED": "YES",
    "BOT_MAINNET_LIMIT_MAKER_VALIDATION_CONFIRMED": "YES",
    "BOT_MAINNET_LIMIT_MAKER_VALIDATION_CLEANUP_CONFIRMED": "YES",
}
DRILL_ERRORS = stream_drill.DRILL_ERRORS
TERMINAL = stream_drill.TERMINAL


def _require_confirmations(environ: Mapping[str, str]) -> None:
    missing = sorted(
        name for name, expected in CONFIRMATIONS.items()
        if environ.get(name) != expected
    )
    if missing:
        raise RuntimeError(
            "Mainnet LIMIT_MAKER validation confirmation missing: "
            + ", ".join(missing)
        )


def _require_no_prior_attempt(path: Path) -> None:
    """Consume at most one exchange mutation attempt for each release."""
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if (
                    isinstance(row, dict)
                    and row.get("product_version") == __version__
                    and row.get("mutation_started") is True
                ):
                    raise RuntimeError(
                        "Mainnet LIMIT_MAKER validation already attempted "
                        f"for release {__version__}"
                    )
    except RuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(
            "Mainnet LIMIT_MAKER validation report cannot prove one-shot status"
        ) from exc


def _build_passive_buy(
    *,
    symbol: str,
    bid: Decimal,
    ask: Decimal,
    rules: dict[str, Decimal],
    notional_usdt: Decimal,
) -> dict[str, str]:
    """Place at the highest non-crossing tick without becoming a taker."""
    if bid <= 0 or ask <= bid:
        raise RuntimeError("Mainnet book ticker is invalid")
    price = round_step(ask - rules["tick"], rules["tick"], "floor")
    if price < bid:
        price = round_step(bid, rules["tick"], "floor")
    if price <= 0 or price >= ask:
        raise RuntimeError("no valid passive LIMIT_MAKER price is available")
    quantity, price_text = normalized_order_values(
        notional_usdt / price,
        price,
        step=rules["step"],
        tick=rules["tick"],
        min_qty=rules["min_qty"],
        min_notional=rules["min_notional"],
        side="BUY",
    )
    actual = decimal(quantity) * decimal(price_text)
    if actual <= 0 or actual > HARD_MAX_NOTIONAL_USDT:
        raise RuntimeError("normalized validation order exceeds the 6 USDT ceiling")
    return {
        "symbol": symbol,
        "side": "BUY",
        "type": "LIMIT_MAKER",
        "quantity": quantity,
        "price": price_text,
        "newOrderRespType": "FULL",
        "newClientOrderId": client_order_id(
            symbol,
            "BUY",
            "maker_validation",
            price_text,
            quantity,
            bucket_seconds=1,
        ),
    }


def _wait_for_fill(
    client: Any,
    *,
    symbol: str,
    order_client_id: str,
    timeout_sec: Decimal,
) -> tuple[dict[str, Any], int]:
    deadline = Decimal(str(time.monotonic())) + timeout_sec
    latest: dict[str, Any] | None = None
    received_at_ms = 0
    while Decimal(str(time.monotonic())) < deadline:
        latest = stream_drill._query_order(client, symbol, order_client_id)
        received_at_ms = int(time.time() * 1000)
        status = str(latest.get("status") or "").upper()
        if decimal(latest.get("executedQty") or "0") > 0 or status in TERMINAL:
            return latest, received_at_ms
        time.sleep(0.2)
    if latest is None:
        latest = stream_drill._query_order(client, symbol, order_client_id)
        received_at_ms = int(time.time() * 1000)
    return latest, received_at_ms


def _trades_for_order(
    client: Any,
    *,
    symbol: str,
    order_id: int,
) -> list[dict[str, Any]]:
    rows = client.signed(
        "GET",
        "/api/v3/myTrades",
        {"symbol": symbol, "orderId": int(order_id), "limit": 1000},
    )
    if not isinstance(rows, list):
        raise RuntimeError("Mainnet trade query returned invalid data")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or int(row.get("orderId", -1)) != order_id:
            raise RuntimeError("Mainnet trade identity is inconsistent")
        result.append(row)
    return sorted(result, key=lambda row: int(row.get("id", -1)))


def _value_trade_commission(
    client: Any,
    *,
    symbol: str,
    trade: Mapping[str, Any],
    cache: dict[tuple[str, str, int], Decimal],
) -> tuple[Decimal, str]:
    value, status = commission_quote_value(
        symbol,
        str(trade.get("commissionAsset") or ""),
        decimal(trade.get("commission") or "0"),
        decimal(trade.get("price") or "0"),
        int(trade.get("time") or 0),
        symbol_assets=lambda _symbol: ("SOL", "USDT"),
        public_get=client.public_get,
        cache=cache,
    )
    if value is None:
        raise RuntimeError("Mainnet validation commission is unpriced")
    return value, status


def _total_trade_commission(
    client: Any,
    *,
    symbol: str,
    trades: list[dict[str, Any]],
) -> Decimal:
    cache: dict[tuple[str, str, int], Decimal] = {}
    total = Decimal("0")
    for trade in trades:
        value, _status = _value_trade_commission(
            client,
            symbol=symbol,
            trade=trade,
            cache=cache,
        )
        total += value
    return total


def _append_maker_evidence(
    path: Path,
    *,
    symbol: str,
    order_client_id: str,
    order_id: int,
    intent_created_at_ms: int,
    order_price: str,
    original_quantity: str,
    final_status: str,
    final_received_at_ms: int,
    trades: list[dict[str, Any]],
    client: Any,
) -> tuple[str, Decimal]:
    """Persist exact trade facts without retaining exchange identifiers."""
    cumulative_quantity = Decimal("0")
    cumulative_quote = Decimal("0")
    total_fee = Decimal("0")
    cache: dict[tuple[str, str, int], Decimal] = {}
    for trade in trades:
        quantity = decimal(trade.get("qty") or "0")
        price = decimal(trade.get("price") or "0")
        if quantity <= 0 or price <= 0 or trade.get("isBuyer") is not True:
            raise RuntimeError("Mainnet maker trade payload is invalid")
        cumulative_quantity += quantity
        cumulative_quote += quantity * price
        fee_quote, fee_status = _value_trade_commission(
            client,
            symbol=symbol,
            trade=trade,
            cache=cache,
        )
        total_fee += fee_quote
        signal = OrderStreamSignal(
            event_time_ms=int(trade.get("time") or 0),
            transaction_time_ms=int(trade.get("time") or 0),
            symbol=symbol,
            order_id=order_id,
            client_order_id=order_client_id,
            execution_type="TRADE",
            order_status=final_status,
            trade_id=int(trade.get("id", -1)),
            side="BUY",
            order_price=order_price,
            original_quantity=original_quantity,
            last_price=format(price, "f"),
            last_quantity=format(quantity, "f"),
            cumulative_quantity=format(cumulative_quantity, "f"),
            cumulative_quote=format(cumulative_quote, "f"),
            commission_amount=str(trade.get("commission") or "0"),
            commission_asset=str(trade.get("commissionAsset") or "").upper(),
            received_time_ms=final_received_at_ms,
            order_type="LIMIT_MAKER",
            stop_price="0",
        )
        append_execution_latency_sample(
            path,
            signal,
            intent_created_at_ms=intent_created_at_ms,
            commission_quote=fee_quote,
            commission_value_status=fee_status,
            observation_source="REST_TERMINAL_QUERY",
        )
    if not trades:
        append_execution_latency_sample(
            path,
            OrderStreamSignal(
                event_time_ms=final_received_at_ms,
                transaction_time_ms=final_received_at_ms,
                symbol=symbol,
                order_id=order_id,
                client_order_id=order_client_id,
                execution_type=final_status,
                order_status=final_status,
                trade_id=-1,
                side="BUY",
                order_price=order_price,
                original_quantity=original_quantity,
                last_price="0",
                last_quantity="0",
                cumulative_quantity="0",
                cumulative_quote="0",
                commission_amount="0",
                commission_asset="",
                received_time_ms=final_received_at_ms,
                order_type="LIMIT_MAKER",
                stop_price="0",
            ),
            intent_created_at_ms=intent_created_at_ms,
            commission_quote=Decimal("0"),
            commission_value_status="not_applicable",
            observation_source="REST_TERMINAL_QUERY",
        )
    order_ref = hashlib.sha256(
        f"{symbol}:{order_id}:{order_client_id}".encode()
    ).hexdigest()[:24]
    return order_ref, total_fee


def _flatten_acquired(
    client: Any,
    journal: OrderJournal,
    *,
    symbol: str,
    base_asset: str,
    initial_base_total: Decimal,
    rules: dict[str, Decimal],
    parent_client_order_id: str,
) -> dict[str, Any] | None:
    account = client.signed("GET", "/api/v3/account")
    current_total = balance_amount(account, base_asset) + balance_amount(
        account, base_asset, "locked"
    )
    acquired = max(Decimal("0"), current_total - initial_base_total)
    quantity = round_step(acquired, rules["step"], "floor")
    if quantity <= rules["step"]:
        return None
    ticker = client.public_get("/api/v3/ticker/price", {"symbol": symbol})
    if quantity < rules["min_qty"] or quantity * decimal(
        ticker["price"]
    ) < rules["min_notional"]:
        raise RuntimeError("acquired validation quantity cannot be cleaned safely")
    quantity_text = format_step(quantity, rules["step"])
    cleanup_id = client_order_id(
        symbol,
        "SELL",
        "maker_validation_cleanup",
        "MARKET",
        quantity_text,
        bucket_seconds=1,
    )
    payload = stream_drill._submit_order(
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
        purpose="maker_validation_cleanup",
        parent_client_order_id=parent_client_order_id,
    )
    if str(payload.get("status") or "").upper() != "FILLED":
        payload = stream_drill._query_order(client, symbol, cleanup_id)
        journal.record_exchange_order(cleanup_id, payload)
    if str(payload.get("status") or "").upper() != "FILLED":
        raise RuntimeError("Mainnet validation cleanup is not FILLED")
    journal.mark_closed(cleanup_id)
    return payload


def run_validation_drill(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] = os.environ,
    client: Any | None = None,
    archive_factory: Callable[..., ContinuousDepthArchive] = (
        ContinuousDepthArchive
    ),
) -> dict[str, Any]:
    """Collect one real passive fill and restore the initial base position."""
    _require_confirmations(environ)
    symbol = str(args.symbol).strip().upper()
    if symbol != ALLOWED_SYMBOL:
        raise RuntimeError(f"validation drill is restricted to {ALLOWED_SYMBOL}")
    requested = decimal(args.notional_usdt)
    wait_sec = decimal(args.wait_sec)
    if requested != HARD_MAX_NOTIONAL_USDT:
        raise RuntimeError("validation drill requires exactly 6 USDT")
    if wait_sec < Decimal("5") or wait_sec > Decimal("180"):
        raise RuntimeError("validation wait must be between 5 and 180 seconds")

    runtime_path = Path(args.runtime)
    state_path = Path(args.state)
    stream_drill._require_halted_shadow(runtime_path)
    observer_before = stream_drill._require_observer(state_path)
    limits = RiskLimits.from_runtime_mapping(environ)
    if limits.reserve_usdt <= 0 or not limits.halt_file.is_file():
        raise RuntimeError("persistent HALT and positive USDT reserve are required")
    report_path = resolve_project_path(args.report)
    batch_manifest = getattr(args, "batch_manifest", None)
    if batch_manifest is None:
        _require_no_prior_attempt(report_path)
    journal_path = resolve_project_path(args.journal)
    production_journal_path = resolve_project_path(args.production_journal)
    execution_log_path = resolve_project_path(args.execution_log)
    archive_directory = resolve_project_path(args.archive_dir)
    if journal_path == production_journal_path:
        raise RuntimeError("validation and production journals must be separate")
    production = read_order_journal_telemetry(production_journal_path)
    if not production.get("available") or int(production.get("pending") or 0):
        raise RuntimeError("production journal is unavailable or nonterminal")
    if client is None:
        api_key = environ.get("BINANCE_API_KEY", "")
        api_secret = environ.get("BINANCE_API_SECRET", "")
        if not api_key or not api_secret:
            raise RuntimeError("BINANCE_API_KEY/SECRET are required")
        client = MainnetCanaryClient(MAINNET_BASE, api_key, api_secret)

    request_started_ms = int(time.time() * 1000)
    server = client.public_get("/api/v3/time")
    response_finished_ms = int(time.time() * 1000)
    assess_exchange_clock(
        server_time_ms=int(server["serverTime"]),
        request_started_ms=request_started_ms,
        response_finished_ms=response_finished_ms,
        max_offset_ms=1000,
        max_round_trip_ms=5000,
    ).require_safe()
    exchange_info = client.public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    rules = symbol_rules(exchange_info)
    base_asset, quote_asset = symbol_assets(exchange_info)
    if (base_asset, quote_asset) != ("SOL", "USDT"):
        raise RuntimeError("validation asset mapping is not SOL/USDT")
    symbol_rows = exchange_info.get("symbols") or []
    if (
        len(symbol_rows) != 1
        or str(symbol_rows[0].get("status") or "").upper() != "TRADING"
        or symbol_rows[0].get("isSpotTradingAllowed") is False
    ):
        raise RuntimeError("SOLUSDT Spot trading is unavailable")
    account_before = client.signed("GET", "/api/v3/account")
    if account_before.get("canTrade") is not True:
        raise RuntimeError("Binance account is not allowed to trade")
    if balance_amount(account_before, quote_asset) - requested < limits.reserve_usdt:
        raise RuntimeError("validation drill would violate the USDT reserve")
    if client.signed("GET", "/api/v3/openOrders", {"symbol": symbol}):
        raise RuntimeError("validation drill requires no open SOLUSDT orders")
    commission_payload = client.signed(
        "GET", "/api/v3/account/commission", {"symbol": symbol}
    )
    schedule = authoritative_commission_schedule(commission_payload)
    estimated_commission = (
        requested
        * Decimal("1.05")
        * (schedule.maker_buy + schedule.taker_sell)
    )
    if estimated_commission > HARD_MAX_COMMISSION_USDT:
        raise RuntimeError("validation commission estimate exceeds 0.03 USDT")
    book = client.public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    params = _build_passive_buy(
        symbol=symbol,
        bid=decimal(book.get("bidPrice")),
        ask=decimal(book.get("askPrice")),
        rules=rules,
        notional_usdt=requested,
    )
    client.signed("POST", "/api/v3/order/test", params)
    journal = OrderJournal(journal_path, venue="mainnet-maker-validation")
    if journal.nonterminal_orders(symbol):
        raise RuntimeError("validation journal contains nonterminal intents")
    initial_base_total = balance_amount(account_before, base_asset) + balance_amount(
        account_before, base_asset, "locked"
    )
    actual_notional = decimal(params["price"]) * decimal(params["quantity"])
    report: dict[str, Any] = {
        "schema_version": 1,
        "product_version": __version__,
        "venue": "mainnet",
        "mode": "limit-maker-validation",
        "symbol": symbol,
        "status": "started",
        "mutation_started": False,
        "notional_limit_usdt": format(actual_notional, "f"),
        "wait_limit_sec": format(wait_sec, "f"),
        "cleanup": "mandatory-market-sell",
        "persistent_halt_required": True,
        "maker_buy_fee_pct": format(schedule.maker_buy, "f"),
        "taker_sell_fee_pct": format(schedule.taker_sell, "f"),
    }
    created: dict[str, Any] | None = None
    final: dict[str, Any] | None = None
    primary_error: BaseException | None = None
    cleanup_done = False
    archive: ContinuousDepthArchive | None = None
    archive_started = False
    try:
        if batch_manifest is not None:
            reservation = reserve_validation_attempt(
                resolve_project_path(batch_manifest),
                drill="LIMIT_MAKER",
                symbol=symbol,
                turnover_usdt=requested * Decimal("2"),
            )
            report["validation_batch_attempt_id"] = reservation["attempt_id"]
            report["validation_batch_manifest_sha256"] = reservation[
                "manifest_sha256"
            ]
        archive = archive_factory(
            symbol=symbol,
            directory=archive_directory,
            label=f"maker-{__version__}",
        )
        archive_path = archive.start()
        archive_started = True
        report["mutation_started"] = True
        # This durable marker consumes the authorized attempt before POST.
        # A process crash must not permit an unreviewed second real order.
        _append_report(report_path, report)
        created = stream_drill._submit_order(
            client, journal, params, purpose="maker_validation"
        )
        observed, final_received_at_ms = _wait_for_fill(
            client,
            symbol=symbol,
            order_client_id=params["newClientOrderId"],
            timeout_sec=wait_sec,
        )
        if str(observed.get("status") or "").upper() in TERMINAL:
            final = observed
            journal.record_exchange_order(params["newClientOrderId"], final)
        else:
            final = stream_drill._cancel_order(
                client,
                journal,
                symbol=symbol,
                order_client_id=params["newClientOrderId"],
            )
            final_received_at_ms = int(time.time() * 1000)
        executed = decimal(final.get("executedQty") or "0")
        trades = (
            _trades_for_order(
                client,
                symbol=symbol,
                order_id=int(final.get("orderId") or 0),
            )
            if executed > 0 else []
        )
        if sum((decimal(row.get("qty") or "0") for row in trades), Decimal("0")) != executed:
            raise RuntimeError("maker fills do not match the terminal order quantity")
        cleanup = _flatten_acquired(
            client,
            journal,
            symbol=symbol,
            base_asset=base_asset,
            initial_base_total=initial_base_total,
            rules=rules,
            parent_client_order_id=params["newClientOrderId"],
        )
        cleanup_done = True
        if executed > 0:
            journal.mark_closed(params["newClientOrderId"])
        observer_after = stream_drill._wait_for_stream_evidence(
            state_path,
            order_events_before=int(observer_before.get("order_events") or 0),
            event_rest_before=int(
                observer_before.get("event_woken_rest_reconciliations") or 0
            ),
        )
        if client.signed("GET", "/api/v3/openOrders", {"symbol": symbol}):
            raise RuntimeError("validation cleanup left an open order")
        account_after = client.signed("GET", "/api/v3/account")
        final_base_total = balance_amount(account_after, base_asset) + balance_amount(
            account_after, base_asset, "locked"
        )
        residual = max(Decimal("0"), final_base_total - initial_base_total)
        if residual > rules["step"]:
            raise RuntimeError("validation cleanup left acquired base inventory")
        order_ref = None
        fee_quote = Decimal("0")
        cleanup_fee_quote = Decimal("0")
        created_at_ms = journal.created_at_ms_for_exchange_order(
            int(final.get("orderId") or 0)
        )
        if created_at_ms is None:
            raise RuntimeError("validation intent timestamp is unavailable")
        order_ref, fee_quote = _append_maker_evidence(
            execution_log_path,
            symbol=symbol,
            order_client_id=params["newClientOrderId"],
            order_id=int(final.get("orderId") or 0),
            intent_created_at_ms=created_at_ms,
            order_price=params["price"],
            original_quantity=params["quantity"],
            final_status=str(final.get("status") or "UNKNOWN").upper(),
            final_received_at_ms=final_received_at_ms,
            trades=trades,
            client=client,
        )
        if executed > 0:
            if cleanup is None or int(cleanup.get("orderId") or 0) <= 0:
                raise RuntimeError("validation cleanup identity is unavailable")
            cleanup_trades = _trades_for_order(
                client,
                symbol=symbol,
                order_id=int(cleanup["orderId"]),
            )
            cleanup_fee_quote = _total_trade_commission(
                client,
                symbol=symbol,
                trades=cleanup_trades,
            )
        total_commission = fee_quote + cleanup_fee_quote
        if total_commission > HARD_MAX_COMMISSION_USDT:
            raise RuntimeError("actual validation commission exceeds 0.03 USDT")
        archive_metadata = archive.stop()
        archive = None
        report.update(
            {
                "status": "passed" if executed > 0 else "no_fill",
                "order_status": str(final.get("status") or "UNKNOWN").upper(),
                "executed_qty": format(executed, "f"),
                "maker_fill_count": len(trades),
                "maker_commission_quote": format(fee_quote, "f"),
                "cleanup_commission_quote": format(cleanup_fee_quote, "f"),
                "total_commission_quote": format(total_commission, "f"),
                "order_ref": order_ref,
                "cleanup_order_filled": cleanup is not None,
                "base_residual_qty": format(residual, "f"),
                "order_events_delta": int(observer_after.get("order_events") or 0)
                - int(observer_before.get("order_events") or 0),
                "event_rest_delta": int(
                    observer_after.get("event_woken_rest_reconciliations") or 0
                ) - int(
                    observer_before.get("event_woken_rest_reconciliations") or 0
                ),
                "archive_path": str(archive_path),
                "archive_sha256": str(
                    archive_metadata.get("archive_sha256") or ""
                ),
            }
        )
        _append_report(report_path, report)
        return report
    except DRILL_ERRORS as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            if report["mutation_started"] and (
                final is None
                or str(final.get("status") or "").upper() not in TERMINAL
            ):
                stream_drill._cancel_order(
                    client,
                    journal,
                    symbol=symbol,
                    order_client_id=params["newClientOrderId"],
                )
            if created is not None and not cleanup_done:
                _flatten_acquired(
                    client,
                    journal,
                    symbol=symbol,
                    base_asset=base_asset,
                    initial_base_total=initial_base_total,
                    rules=rules,
                    parent_client_order_id=params["newClientOrderId"],
                )
            if archive is not None and archive_started:
                archive.stop()
        except DRILL_ERRORS as exc:
            cleanup_error = exc
        if primary_error is not None or cleanup_error is not None:
            create_manual_halt(
                "Mainnet LIMIT_MAKER validation failed closed",
                limits=limits,
                metadata={"symbol": symbol, "purpose": "maker-validation"},
            )
            report.update(
                {
                    "status": "failed",
                    "error_type": type(primary_error or cleanup_error).__name__,
                    "mutation_started": bool(report["mutation_started"]),
                }
            )
            if report["mutation_started"]:
                _append_report(report_path, report)
            if primary_error is not None:
                if cleanup_error is not None:
                    raise primary_error from cleanup_error
                raise primary_error
            raise RuntimeError(
                "Mainnet LIMIT_MAKER validation failed closed"
            ) from cleanup_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-shot Mainnet LIMIT_MAKER validation drill"
    )
    parser.add_argument("--symbol", default=ALLOWED_SYMBOL)
    parser.add_argument(
        "--notional-usdt", type=Decimal, default=HARD_MAX_NOTIONAL_USDT
    )
    parser.add_argument("--wait-sec", type=Decimal, default=DEFAULT_WAIT_SEC)
    parser.add_argument("--runtime", type=Path, default=stream_drill.RUNTIME_PATH)
    parser.add_argument("--state", type=Path, default=stream_drill.STATE_PATH)
    parser.add_argument(
        "--journal", default="db/mainnet_maker_validation_order_intents.sqlite3"
    )
    parser.add_argument(
        "--production-journal",
        default=os.getenv("BOT_ORDER_JOURNAL", "db/order_intents.sqlite3"),
    )
    parser.add_argument("--report", default="logs/mainnet_maker_validation.ndjson")
    parser.add_argument("--batch-manifest", default=None)
    parser.add_argument("--execution-log", default="logs/execution_latency.ndjson")
    parser.add_argument(
        "--archive-dir", default="logs/replay-validation-archives"
    )
    parser.add_argument(
        "--lock-file", default=".runtime/mainnet-maker-validation.lock"
    )
    return parser


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env")
    parser = build_parser()
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol.strip().upper()):
        parser.error("--symbol must be an uppercase Binance symbol")
    print(
        json.dumps(
            {
                "venue": "mainnet",
                "mode": "limit-maker-validation",
                "symbol": args.symbol.strip().upper(),
                "hard_max_notional_usdt": str(HARD_MAX_NOTIONAL_USDT),
                "cleanup": "mandatory-market-sell",
                "requires_halt": True,
                "one_attempt_per_release": args.batch_manifest is None,
                "bounded_batch": args.batch_manifest is not None,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        with exclusive_lock(args.lock_file):
            report = run_validation_drill(args)
    except DRILL_ERRORS as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:240],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


__all__ = ["build_parser", "run_validation_drill"]
