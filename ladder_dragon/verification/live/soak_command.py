# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a Testnet soak boundary without changing monitoring behavior.
"""Testnet soak_command implementation."""

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time

from dotenv import load_dotenv
from ladder_dragon.execution.venue_config import apply_testnet_paths
from ladder_dragon.verification.live.testnet_smoke import SpotTestnetClient, symbol_rules, symbol_assets
from ladder_dragon.verification.live.soak_policy import SoakSample, evaluate_sample, _advance_grace
from ladder_dragon.verification.live.soak_sources import _read_sources
from ladder_dragon.verification.live.soak_reports import _atomic_report, _json_sample, _finish_report
from ladder_dragon.verification.live.soak_parser import _parse_monitor_args


RUN = True


SOAK_SOURCE_ERRORS = (
    ArithmeticError,
    KeyError,
    RuntimeError,
    sqlite3.Error,
    TypeError,
    ValueError,
)


def _stop(_signum: int, _frame: object) -> None:
    global RUN
    RUN = False


def main() -> int:
    load_dotenv()
    apply_testnet_paths()
    parser, args, symbol = _parse_monitor_args()

    client = SpotTestnetClient(
        os.getenv("BINANCE_TESTNET_API_BASE", "https://testnet.binance.vision"),
        os.getenv("BINANCE_TESTNET_API_KEY", ""),
        os.getenv("BINANCE_TESTNET_API_SECRET", ""),
    )
    info = client.public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    rules = symbol_rules(info)
    base_asset, quote_asset = symbol_assets(info)
    if quote_asset != "USDT":
        parser.error("soak monitor currently requires a USDT quote symbol")
    db_path = os.environ.get("BOT_STATS_DB", "").strip()
    if not db_path or not Path(db_path).is_file():
        parser.error("isolated BOT_TESTNET_STATS_DB must exist")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    started = time.monotonic()
    unprotected_since: float | None = None
    mismatch_since: float | None = None
    samples = 0
    max_seen_exposure = Decimal("0")
    max_seen_buys = 0
    last_sample: SoakSample | None = None
    status = "pass"
    reasons: list[str] = []
    read_failures = 0
    consecutive_read_failures = 0
    max_consecutive_read_failures = 0
    last_source_error: str | None = None

    while RUN:
        try:
            (account_qty, ledger_qty, price, open_buys, open_sells, protected_legs,
             protected_qty, protection_complete, open_buy_exposure, holdings) = (
                _read_sources(client, symbol, base_asset, db_path, rules))
        except SOAK_SOURCE_ERRORS as exc:
            read_failures += 1
            consecutive_read_failures += 1
            max_consecutive_read_failures = max(
                max_consecutive_read_failures, consecutive_read_failures
            )
            last_source_error = type(exc).__name__
            print(
                f"[SOAK-WARN] source read failed: {last_source_error}",
                file=sys.stderr,
            )
            elapsed = time.monotonic() - started
            exhausted = consecutive_read_failures >= args.max_consecutive_read_failures
            if exhausted or elapsed >= args.duration_sec:
                status = "source_unavailable"
                reasons = [
                    "data source remained unavailable during the Testnet soak"
                ]
                break
            _atomic_report(
                Path(args.report),
                {
                    "status": "running_degraded",
                    "symbol": symbol,
                    "duration_sec": round(elapsed, 3),
                    "samples": samples,
                    "read_failures": read_failures,
                    "consecutive_read_failures": consecutive_read_failures,
                    "max_consecutive_read_failures": max_consecutive_read_failures,
                    "last_source_error": last_source_error,
                    "reasons": ["data source read failed; retry scheduled"],
                    "last_sample": _json_sample(last_sample) if last_sample else None,
                },
            )
            time.sleep(min(args.interval_sec, args.duration_sec - elapsed))
            continue
        consecutive_read_failures = 0
        sample = SoakSample(
            ts=time.time(),
            account_qty=account_qty,
            ledger_qty=ledger_qty,
            market_price=price,
            holdings_exposure=holdings,
            total_exposure=holdings + open_buy_exposure,
            open_buy_count=len(open_buys),
            open_sell_count=len(open_sells),
            protected_sell_legs=protected_legs,
            protected_sell_qty=protected_qty,
            protection_complete=protection_complete,
            halted=(Path(os.environ["BOT_RUN_DIR"]) / "circuit_halt.json").exists(),
        )
        samples += 1
        last_sample = sample
        max_seen_exposure = max(max_seen_exposure, sample.total_exposure)
        max_seen_buys = max(max_seen_buys, sample.open_buy_count)
        immediate, unprotected, mismatch = evaluate_sample(
            sample,
            max_open_buys=args.max_open_buys,
            max_exposure=args.max_exposure_usdt,
            min_notional=rules["min_notional"],
            quantity_tolerance=rules["step"],
        )
        now = time.monotonic()
        unprotected_since, mismatch_since, reasons = _advance_grace(
            unprotected, mismatch, unprotected_since, mismatch_since, now, immediate, args)
        if reasons:
            status = "violation"
            break
        if now - started >= args.duration_sec:
            break
        time.sleep(min(args.interval_sec, max(0.0, args.duration_sec - (now - started))))

    if not RUN and status == "pass":
        status = "interrupted"
    return _finish_report(
        args, status, symbol, started, samples, max_seen_exposure, max_seen_buys,
        read_failures, max_consecutive_read_failures, last_source_error, reasons, last_sample)
