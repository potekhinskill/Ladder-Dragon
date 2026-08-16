#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: monitor a long-running Spot Testnet session.
"""Read-only Binance Spot Testnet safety monitor for long soak runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
import tempfile
import time
from typing import Any

from dotenv import load_dotenv

from ladder_dragon.verification.live.testnet_smoke import (
    SpotTestnetClient,
    balance_amount,
    symbol_assets,
    symbol_rules,
)
from ladder_dragon.execution.exchange_math import decimal
from ladder_dragon.execution.venue_config import apply_testnet_paths


RUN = True
SOAK_SOURCE_ERRORS = (
    ArithmeticError,
    KeyError,
    RuntimeError,
    sqlite3.Error,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class SoakSample:
    ts: float
    account_qty: Decimal
    ledger_qty: Decimal
    market_price: Decimal
    holdings_exposure: Decimal
    total_exposure: Decimal
    open_buy_count: int
    open_sell_count: int
    protected_sell_legs: int
    protected_sell_qty: Decimal
    protection_complete: bool
    halted: bool


def evaluate_sample(
    sample: SoakSample,
    *,
    max_open_buys: int,
    max_exposure: Decimal,
    min_notional: Decimal,
    quantity_tolerance: Decimal,
) -> tuple[list[str], bool, bool]:
    violations: list[str] = []
    if sample.open_buy_count > max_open_buys:
        violations.append(
            f"open BUY count {sample.open_buy_count} exceeds {max_open_buys}"
        )
    if sample.total_exposure > max_exposure:
        violations.append(
            f"exposure {sample.total_exposure} exceeds {max_exposure} USDT"
        )
    if sample.halted:
        violations.append("persistent Testnet circuit halt exists")
    unprotected = (
        sample.holdings_exposure >= min_notional
        and (
            not sample.protection_complete
            or sample.protected_sell_qty + quantity_tolerance < sample.account_qty
        )
    )
    mismatch = abs(sample.account_qty - sample.ledger_qty) > quantity_tolerance
    return violations, unprotected, mismatch


def oco_protection_coverage(
    open_sells: list[dict[str, Any]],
    *,
    quantity_tolerance: Decimal,
) -> tuple[int, Decimal, bool]:
    """Return OCO leg count, protected quantity, and structural completeness."""
    groups: dict[int, list[dict[str, Any]]] = {}
    protected_legs = 0
    for row in open_sells:
        order_list_id = int(row.get("orderListId", -1))
        if order_list_id < 0:
            continue
        protected_legs += 1
        groups.setdefault(order_list_id, []).append(row)

    covered = Decimal("0")
    complete = bool(groups)
    for legs in groups.values():
        if len(legs) != 2:
            complete = False
            continue
        remaining = [
            decimal(row.get("origQty")) - decimal(row.get("executedQty"))
            for row in legs
        ]
        if any(qty <= 0 for qty in remaining):
            complete = False
            continue
        if abs(remaining[0] - remaining[1]) > quantity_tolerance:
            complete = False
            continue
        # Two OCO legs protect one shared quantity. Never add both legs.
        covered += min(remaining)
    return protected_legs, covered, complete


def _inventory_qty(db_path: str, symbol: str) -> Decimal:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as con:
        row = con.execute(
            "SELECT qty_text FROM inventory_exact WHERE symbol=?", (symbol,)
        ).fetchone()
    return decimal(row[0]) if row else Decimal("0")


def _atomic_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _json_sample(sample: SoakSample) -> dict[str, Any]:
    payload = asdict(sample)
    for key, value in list(payload.items()):
        if isinstance(value, Decimal):
            payload[key] = format(value, "f")
    return payload


def _stop(_signum: int, _frame: object) -> None:
    global RUN
    RUN = False


def main() -> int:
    load_dotenv()
    apply_testnet_paths()
    parser = argparse.ArgumentParser(
        description="Read-only invariant monitor for Binance Spot Testnet soak runs"
    )
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--duration-sec", type=int, default=43_200)
    parser.add_argument("--interval-sec", type=float, default=5.0)
    parser.add_argument("--max-open-buys", type=int, default=1)
    parser.add_argument(
        "--max-exposure-usdt",
        type=Decimal,
        default=Decimal(os.getenv("RISK_PORTFOLIO_CAP_USDT", "25")),
    )
    parser.add_argument("--grace-sec", type=float, default=10.0)
    parser.add_argument("--max-consecutive-read-failures", type=int, default=12)
    parser.add_argument(
        "--report",
        default=str(Path(os.environ["BOT_RUN_DIR"]) / "soak_report.json"),
    )
    args = parser.parse_args()
    symbol = args.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol):
        parser.error("--symbol must be a valid uppercase Binance symbol")
    if args.duration_sec < 0 or args.interval_sec <= 0 or args.grace_sec < 0:
        parser.error("duration/grace must be non-negative and interval must be > 0")
    if args.max_open_buys < 0 or args.max_exposure_usdt <= 0:
        parser.error("BUY count must be non-negative and exposure must be > 0")
    if args.max_consecutive_read_failures <= 0:
        parser.error("--max-consecutive-read-failures must be > 0")

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
            account = client.signed("GET", "/api/v3/account")
            orders = client.signed(
                "GET", "/api/v3/openOrders", {"symbol": symbol}
            )
            price = decimal(
                client.public_get(
                    "/api/v3/ticker/price", {"symbol": symbol}
                )["price"]
            )
            account_qty = balance_amount(account, base_asset) + balance_amount(
                account, base_asset, "locked"
            )
            ledger_qty = _inventory_qty(db_path, symbol)
            open_buys = [
                row for row in orders if str(row.get("side")).upper() == "BUY"
            ]
            open_sells = [
                row for row in orders if str(row.get("side")).upper() == "SELL"
            ]
            protected_legs, protected_qty, protection_complete = (
                oco_protection_coverage(
                    open_sells,
                    quantity_tolerance=rules["step"],
                )
            )
            open_buy_exposure = sum(
                decimal(row.get("price"))
                * (decimal(row.get("origQty")) - decimal(row.get("executedQty")))
                for row in open_buys
            )
            holdings = account_qty * price
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
        if unprotected:
            unprotected_since = unprotected_since if unprotected_since is not None else now
        else:
            unprotected_since = None
        if mismatch:
            mismatch_since = mismatch_since if mismatch_since is not None else now
        else:
            mismatch_since = None
        reasons = list(immediate)
        if unprotected_since is not None and now - unprotected_since > args.grace_sec:
            reasons.append("tradable position remained without two verified OCO legs")
        if mismatch_since is not None and now - mismatch_since > args.grace_sec:
            reasons.append("exchange account and SQLite inventory remained inconsistent")
        if reasons:
            status = "violation"
            break
        if now - started >= args.duration_sec:
            break
        time.sleep(min(args.interval_sec, max(0.0, args.duration_sec - (now - started))))

    if not RUN and status == "pass":
        status = "interrupted"
    report = {
        "status": status,
        "symbol": symbol,
        "duration_sec": round(time.monotonic() - started, 3),
        "samples": samples,
        "max_seen_exposure_usdt": format(max_seen_exposure, "f"),
        "max_seen_open_buys": max_seen_buys,
        "read_failures": read_failures,
        "max_consecutive_read_failures": max_consecutive_read_failures,
        "last_source_error": last_source_error,
        "reasons": reasons,
        "last_sample": _json_sample(last_sample) if last_sample else None,
    }
    _atomic_report(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if status in {"violation", "source_unavailable"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
