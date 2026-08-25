# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect one bounded Mainnet STOP_LOSS_LIMIT outcome for replay validation.
"""Run one fail-closed Mainnet STOP_LOSS_LIMIT validation under HALT."""

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

from ladder_dragon.execution.exchange_math import decimal
from ladder_dragon.execution.execution_latency import (
    append_execution_latency_sample,
)
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
from ladder_dragon.verification.live.mainnet_limit_maker_validation import (
    HARD_MAX_COMMISSION_USDT,
    _flatten_acquired,
    _total_trade_commission,
    _trades_for_order,
    _value_trade_commission,
)
from ladder_dragon.verification.live.testnet_smoke import (
    _submit_market_buy,
    _submit_oco,
    balance_amount,
    build_market_buy,
    build_oco_sell,
    symbol_assets,
    symbol_rules,
)
from ladder_dragon.verification.live.validation_archive import (
    ContinuousDepthArchive,
)
from ladder_dragon.verification.live.validation_batch import (
    complete_validation_attempt,
    reserve_validation_attempt,
)
from product_version import __version__


HARD_MAX_NOTIONAL_USDT = Decimal("6")
DEFAULT_WAIT_SEC = Decimal("300")
TAKE_PROFIT_PCT = Decimal("0.05")
STOP_LOSS_PCT = Decimal("0.001")
STOP_LIMIT_OFFSET_PCT = Decimal("0.0005")
CONFIRMATIONS = {
    "BOT_LIVE_CONFIRMED": "YES",
    "BOT_MAINNET_STOP_LIMIT_VALIDATION_CONFIRMED": "YES",
    "BOT_MAINNET_STOP_LIMIT_VALIDATION_CLEANUP_CONFIRMED": "YES",
}
DRILL_ERRORS = stream_drill.DRILL_ERRORS + (AttributeError, KeyError)


def _require_confirmations(environ: Mapping[str, str]) -> None:
    missing = sorted(
        name for name, expected in CONFIRMATIONS.items()
        if environ.get(name) != expected
    )
    if missing:
        raise RuntimeError(
            "Mainnet STOP_LOSS_LIMIT validation confirmation missing: "
            + ", ".join(missing)
        )


def _require_no_prior_attempt(path: Path) -> None:
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                isinstance(row, dict)
                and row.get("product_version") == __version__
                and row.get("mutation_started") is True
            ):
                raise RuntimeError(
                    "Mainnet STOP_LOSS_LIMIT validation already attempted "
                    f"for release {__version__}"
                )
    except RuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(
            "Mainnet STOP_LOSS_LIMIT report cannot prove one-shot status"
        ) from exc


def _cancel_order_list(
    client: Any,
    *,
    symbol: str,
    order_list_id: int,
) -> dict[str, Any]:
    latest = client.signed(
        "GET", "/api/v3/orderList", {"orderListId": order_list_id}
    )
    if str(latest.get("listStatusType") or "").upper() == "ALL_DONE":
        return latest
    try:
        client.signed(
            "DELETE",
            "/api/v3/orderList",
            {"symbol": symbol, "orderListId": order_list_id},
        )
    except requests.RequestException:
        pass
    latest = client.signed(
        "GET", "/api/v3/orderList", {"orderListId": order_list_id}
    )
    if str(latest.get("listStatusType") or "").upper() != "ALL_DONE":
        raise RuntimeError("Mainnet validation OCO cancellation is uncertain")
    return latest


def _wait_for_order_list(
    client: Any,
    *,
    order_list_id: int,
    timeout_sec: Decimal,
) -> dict[str, Any]:
    deadline = Decimal(str(time.monotonic())) + timeout_sec
    latest: dict[str, Any] | None = None
    while Decimal(str(time.monotonic())) < deadline:
        latest = client.signed(
            "GET", "/api/v3/orderList", {"orderListId": order_list_id}
        )
        if str(latest.get("listStatusType") or "").upper() == "ALL_DONE":
            return latest
        time.sleep(0.2)
    return latest or {}


def _append_leg_evidence(
    path: Path,
    *,
    client: Any,
    symbol: str,
    leg: Mapping[str, Any],
    intent_created_at_ms: int,
    received_at_ms: int,
) -> tuple[str, Decimal]:
    """Append exact REST facts for one terminal OCO leg."""
    order_id = int(leg.get("orderId") or 0)
    client_id = str(leg.get("clientOrderId") or "")
    order_type = str(leg.get("type") or "").upper()
    if order_id <= 0 or not client_id:
        raise RuntimeError("Mainnet validation OCO leg identity is unavailable")
    if order_type not in {"LIMIT_MAKER", "LIMIT", "STOP_LOSS_LIMIT"}:
        raise RuntimeError("Mainnet validation OCO leg type is unsupported")
    trades = _trades_for_order(client, symbol=symbol, order_id=order_id)
    cumulative_quantity = Decimal("0")
    cumulative_quote = Decimal("0")
    total_fee = Decimal("0")
    cache: dict[tuple[str, str, int], Decimal] = {}
    signals: list[tuple[OrderStreamSignal, Decimal | None, str]] = []
    for trade in trades:
        quantity = decimal(trade.get("qty") or "0")
        price = decimal(trade.get("price") or "0")
        if quantity <= 0 or price <= 0 or trade.get("isBuyer") is not False:
            raise RuntimeError("Mainnet validation SELL trade is invalid")
        cumulative_quantity += quantity
        cumulative_quote += quantity * price
        fee_quote, fee_status = _value_trade_commission(
            client,
            symbol=symbol,
            trade=trade,
            cache=cache,
        )
        total_fee += fee_quote
        signals.append(
            (
                OrderStreamSignal(
                    event_time_ms=int(trade.get("time") or 0),
                    transaction_time_ms=int(trade.get("time") or 0),
                    symbol=symbol,
                    order_id=order_id,
                    client_order_id=client_id,
                    execution_type="TRADE",
                    order_status=str(leg.get("status") or "UNKNOWN").upper(),
                    trade_id=int(trade.get("id", -1)),
                    side="SELL",
                    order_price=str(leg.get("price") or "0"),
                    original_quantity=str(leg.get("origQty") or "0"),
                    last_price=format(price, "f"),
                    last_quantity=format(quantity, "f"),
                    cumulative_quantity=format(cumulative_quantity, "f"),
                    cumulative_quote=format(cumulative_quote, "f"),
                    commission_amount=str(trade.get("commission") or "0"),
                    commission_asset=str(
                        trade.get("commissionAsset") or ""
                    ).upper(),
                    received_time_ms=received_at_ms,
                    order_type=order_type,
                    stop_price=str(leg.get("stopPrice") or "0"),
                ),
                fee_quote,
                fee_status,
            )
        )
    if not signals:
        signals.append(
            (
                OrderStreamSignal(
                    event_time_ms=int(leg.get("updateTime") or received_at_ms),
                    transaction_time_ms=int(
                        leg.get("updateTime") or received_at_ms
                    ),
                    symbol=symbol,
                    order_id=order_id,
                    client_order_id=client_id,
                    execution_type=str(leg.get("status") or "CANCELED").upper(),
                    order_status=str(leg.get("status") or "UNKNOWN").upper(),
                    trade_id=-1,
                    side="SELL",
                    order_price=str(leg.get("price") or "0"),
                    original_quantity=str(leg.get("origQty") or "0"),
                    last_price="0",
                    last_quantity="0",
                    cumulative_quantity=str(leg.get("executedQty") or "0"),
                    cumulative_quote=str(leg.get("cummulativeQuoteQty") or "0"),
                    commission_amount="0",
                    commission_asset="",
                    received_time_ms=received_at_ms,
                    order_type=order_type,
                    stop_price=str(leg.get("stopPrice") or "0"),
                ),
                Decimal("0"),
                "not_applicable",
            )
        )
    for signal, fee_quote, fee_status in signals:
        append_execution_latency_sample(
            path,
            signal,
            intent_created_at_ms=intent_created_at_ms,
            commission_quote=fee_quote,
            commission_value_status=fee_status,
            observation_source="REST_TERMINAL_QUERY",
        )
    order_ref = hashlib.sha256(
        f"{symbol}:{order_id}:{client_id}".encode()
    ).hexdigest()[:24]
    return order_ref, total_fee


def run_validation_drill(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] = os.environ,
    client: Any | None = None,
    archive_factory: Callable[..., ContinuousDepthArchive] = (
        ContinuousDepthArchive
    ),
) -> dict[str, Any]:
    """Collect one typed OCO outcome and restore the initial base position."""
    _require_confirmations(environ)
    symbol = str(args.symbol).strip().upper()
    requested = decimal(args.notional_usdt)
    wait_sec = decimal(args.wait_sec)
    if symbol != ALLOWED_SYMBOL or requested != HARD_MAX_NOTIONAL_USDT:
        raise RuntimeError("STOP_LOSS_LIMIT validation requires SOLUSDT and 6 USDT")
    if wait_sec < Decimal("30") or wait_sec > Decimal("900"):
        raise RuntimeError("STOP_LOSS_LIMIT wait must be between 30 and 900 seconds")
    stream_drill._require_halted_shadow(Path(args.runtime))
    observer_before = stream_drill._require_observer(Path(args.state))
    limits = RiskLimits.from_runtime_mapping(environ)
    if limits.reserve_usdt <= 0 or not limits.halt_file.is_file():
        raise RuntimeError("persistent HALT and positive USDT reserve are required")
    report_path = resolve_project_path(args.report)
    batch_manifest = getattr(args, "batch_manifest", None)
    if batch_manifest is None:
        _require_no_prior_attempt(report_path)
    journal_path = resolve_project_path(args.journal)
    production_path = resolve_project_path(args.production_journal)
    if journal_path == production_path:
        raise RuntimeError("validation and production journals must be separate")
    production = read_order_journal_telemetry(production_path)
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
    estimated_commission = requested * Decimal("2.1") * max(
        schedule.taker_buy, schedule.taker_sell
    )
    if estimated_commission > HARD_MAX_COMMISSION_USDT:
        raise RuntimeError("validation commission estimate exceeds 0.03 USDT")
    journal = OrderJournal(journal_path, venue="mainnet-stop-validation")
    if journal.nonterminal_orders(symbol):
        raise RuntimeError("validation journal contains nonterminal intents")
    initial_base = balance_amount(account_before, base_asset) + balance_amount(
        account_before, base_asset, "locked"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "product_version": __version__,
        "venue": "mainnet",
        "mode": "stop-loss-limit-validation",
        "symbol": symbol,
        "status": "started",
        "mutation_started": False,
        "notional_limit_usdt": "6",
        "stop_loss_pct": format(STOP_LOSS_PCT, "f"),
        "stop_limit_offset_pct": format(STOP_LIMIT_OFFSET_PCT, "f"),
        "persistent_halt_required": True,
    }
    buy: dict[str, Any] | None = None
    oco: dict[str, Any] | None = None
    archive: ContinuousDepthArchive | None = None
    archive_started = False
    archive_path: Path | None = None
    archive_metadata: dict[str, object] = {}
    reservation: dict[str, object] | None = None
    cleanup_done = False
    primary_error: BaseException | None = None
    try:
        if batch_manifest is not None:
            reservation = reserve_validation_attempt(
                resolve_project_path(batch_manifest),
                drill="STOP_LOSS_LIMIT",
                symbol=symbol,
                turnover_usdt=requested * Decimal("2"),
            )
            report["validation_batch_attempt_id"] = reservation["attempt_id"]
            report["validation_batch_manifest_sha256"] = reservation[
                "manifest_sha256"
            ]
        archive = archive_factory(
            symbol=symbol,
            directory=resolve_project_path(args.archive_dir),
            label=f"stop-{__version__}",
        )
        archive_path = archive.start()
        archive_started = True
        report["mutation_started"] = True
        _append_report(report_path, report)
        buy_params = build_market_buy(
            symbol, requested, purpose_prefix="stop_validation"
        )
        buy = _submit_market_buy(
            client,
            journal,
            buy_params,
            purpose_prefix="stop_validation",
            venue_label="Mainnet validation",
        )
        account_after_buy = client.signed("GET", "/api/v3/account")
        acquired = max(
            Decimal("0"),
            balance_amount(account_after_buy, base_asset) - initial_base,
        )
        ticker = client.public_get("/api/v3/ticker/price", {"symbol": symbol})
        oco_params = build_oco_sell(
            symbol=symbol,
            quantity=acquired,
            market_price=ticker["price"],
            rules=rules,
            parent_client_order_id=buy_params["newClientOrderId"],
            take_profit_pct=TAKE_PROFIT_PCT,
            stop_loss_pct=STOP_LOSS_PCT,
            stop_limit_offset_pct=STOP_LIMIT_OFFSET_PCT,
            purpose_prefix="stop_validation",
        )
        oco = _submit_oco(
            client,
            journal,
            oco_params,
            buy_params["newClientOrderId"],
            purpose_prefix="stop_validation",
            venue_label="Mainnet validation",
        )
        order_list_id = int(oco.get("orderListId") or 0)
        if order_list_id <= 0:
            raise RuntimeError("validation OCO list identity is unavailable")
        terminal_list = _wait_for_order_list(
            client,
            order_list_id=order_list_id,
            timeout_sec=wait_sec,
        )
        if str(terminal_list.get("listStatusType") or "").upper() != "ALL_DONE":
            terminal_list = _cancel_order_list(
                client, symbol=symbol, order_list_id=order_list_id
            )
        received_at_ms = int(time.time() * 1000)
        refs = terminal_list.get("orders") or oco.get("orders") or []
        if len(refs) != 2:
            raise RuntimeError("terminal validation OCO has invalid legs")
        legs = [
            client.signed(
                "GET",
                "/api/v3/order",
                {"symbol": symbol, "orderId": int(ref["orderId"])},
            )
            for ref in refs
        ]
        if any(
            str(leg.get("status") or "").upper() not in stream_drill.TERMINAL
            for leg in legs
        ):
            raise RuntimeError("validation OCO contains a nonterminal leg")
        order_refs: list[str] = []
        evidence_fee = Decimal("0")
        stop_filled = False
        for leg in legs:
            created_at_ms = journal.created_at_ms_for_exchange_order(
                int(leg.get("orderId") or 0)
            )
            if created_at_ms is None:
                raise RuntimeError("validation OCO leg timestamp is unavailable")
            order_ref, fee_quote = _append_leg_evidence(
                resolve_project_path(args.execution_log),
                client=client,
                symbol=symbol,
                leg=leg,
                intent_created_at_ms=created_at_ms,
                received_at_ms=received_at_ms,
            )
            order_refs.append(order_ref)
            evidence_fee += fee_quote
            stop_filled = stop_filled or (
                str(leg.get("type") or "").upper() == "STOP_LOSS_LIMIT"
                and decimal(leg.get("executedQty") or "0") > 0
            )
        cleanup = _flatten_acquired(
            client,
            journal,
            symbol=symbol,
            base_asset=base_asset,
            initial_base_total=initial_base,
            rules=rules,
            parent_client_order_id=buy_params["newClientOrderId"],
        )
        cleanup_done = True
        cleanup_fee = Decimal("0")
        if cleanup is not None:
            cleanup_fee = _total_trade_commission(
                client,
                symbol=symbol,
                trades=_trades_for_order(
                    client,
                    symbol=symbol,
                    order_id=int(cleanup.get("orderId") or 0),
                ),
            )
        if evidence_fee + cleanup_fee > HARD_MAX_COMMISSION_USDT:
            raise RuntimeError("actual validation commission exceeds 0.03 USDT")
        journal.mark_closed(oco_params["listClientOrderId"])
        journal.mark_closed(buy_params["newClientOrderId"])
        if client.signed("GET", "/api/v3/openOrders", {"symbol": symbol}):
            raise RuntimeError("validation cleanup left an open order")
        observer_after = stream_drill._wait_for_stream_evidence(
            Path(args.state),
            order_events_before=int(observer_before.get("order_events") or 0),
            event_rest_before=int(
                observer_before.get("event_woken_rest_reconciliations") or 0
            ),
        )
        archive_metadata = archive.stop()
        archive = None
        report.update(
            {
                "status": "passed" if stop_filled else "no_stop_fill",
                "stop_filled": stop_filled,
                "order_refs": order_refs,
                "total_commission_quote": format(
                    evidence_fee + cleanup_fee, "f"
                ),
                "archive_path": str(archive_path),
                "archive_sha256": str(
                    archive_metadata.get("archive_sha256") or ""
                ),
                "order_events_delta": int(
                    observer_after.get("order_events") or 0
                ) - int(observer_before.get("order_events") or 0),
                "event_rest_delta": int(
                    observer_after.get("event_woken_rest_reconciliations") or 0
                ) - int(
                    observer_before.get("event_woken_rest_reconciliations") or 0
                ),
            }
        )
        _append_report(report_path, report)
        if reservation is not None:
            complete_validation_attempt(
                resolve_project_path(batch_manifest),
                attempt_id=str(reservation["attempt_id"]),
                status="SUCCEEDED",
                archive_path=str(archive_path),
                archive_sha256=str(archive_metadata.get("archive_sha256") or ""),
                order_refs=tuple(str(item) for item in order_refs if str(item)),
            )
            reservation = None
        return report
    except DRILL_ERRORS as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            if oco is not None:
                order_list_id = int(oco.get("orderListId") or 0)
                if order_list_id > 0:
                    _cancel_order_list(
                        client, symbol=symbol, order_list_id=order_list_id
                    )
            if buy is not None and not cleanup_done:
                _flatten_acquired(
                    client,
                    journal,
                    symbol=symbol,
                    base_asset=base_asset,
                    initial_base_total=initial_base,
                    rules=rules,
                    parent_client_order_id=str(
                        buy.get("clientOrderId") or "stop_validation"
                    ),
                )
            if archive is not None and archive_started:
                archive_metadata = archive.stop()
                archive = None
        except DRILL_ERRORS as exc:
            cleanup_error = exc
        if primary_error is not None or cleanup_error is not None:
            create_manual_halt(
                "Mainnet STOP_LOSS_LIMIT validation failed closed",
                limits=limits,
                metadata={"symbol": symbol, "purpose": "stop-validation"},
            )
            report.update(
                {
                    "status": "failed",
                    "error_type": type(primary_error or cleanup_error).__name__,
                }
            )
            if archive_path is not None:
                report["archive_path"] = str(archive_path)
            if archive_metadata.get("archive_sha256"):
                report["archive_sha256"] = str(
                    archive_metadata["archive_sha256"]
                )
            if report["mutation_started"]:
                _append_report(report_path, report)
            if reservation is not None:
                complete_validation_attempt(
                    resolve_project_path(batch_manifest),
                    attempt_id=str(reservation["attempt_id"]),
                    status="FAILED_UNCERTAIN",
                    archive_path=(str(archive_path) if archive_path else None),
                    archive_sha256=str(
                        archive_metadata.get("archive_sha256") or ""
                    ),
                )
                reservation = None
            if primary_error is not None:
                if cleanup_error is not None:
                    raise primary_error from cleanup_error
                raise primary_error
            raise RuntimeError(
                "Mainnet STOP_LOSS_LIMIT validation failed closed"
            ) from cleanup_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-shot Mainnet STOP_LOSS_LIMIT validation drill"
    )
    parser.add_argument("--symbol", default=ALLOWED_SYMBOL)
    parser.add_argument("--notional-usdt", type=Decimal, default=Decimal("6"))
    parser.add_argument("--wait-sec", type=Decimal, default=DEFAULT_WAIT_SEC)
    parser.add_argument("--runtime", type=Path, default=stream_drill.RUNTIME_PATH)
    parser.add_argument("--state", type=Path, default=stream_drill.STATE_PATH)
    parser.add_argument(
        "--journal", default="db/mainnet_stop_validation_order_intents.sqlite3"
    )
    parser.add_argument(
        "--production-journal",
        default=os.getenv("BOT_ORDER_JOURNAL", "db/order_intents.sqlite3"),
    )
    parser.add_argument("--report", default="logs/mainnet_stop_validation.ndjson")
    parser.add_argument("--batch-manifest", default=None)
    parser.add_argument("--execution-log", default="logs/execution_latency.ndjson")
    parser.add_argument(
        "--archive-dir", default="logs/replay-validation-archives"
    )
    parser.add_argument(
        "--lock-file", default=".runtime/mainnet-stop-validation.lock"
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
                "mode": "stop-loss-limit-validation",
                "symbol": args.symbol.strip().upper(),
                "hard_max_notional_usdt": "6",
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
