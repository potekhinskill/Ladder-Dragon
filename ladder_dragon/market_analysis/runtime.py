# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: orchestrate public multi-symbol SHADOW scenario collection.
"""Observation-only market scenario service."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable, Sequence

import requests

from ladder_dragon.market_analysis.binance_public import fetch_closed_klines
from ladder_dragon.market_analysis.config import prove_execution_scope_unchanged
from ladder_dragon.market_analysis.store import MarketScenarioStore
from ladder_dragon.strategy.scenario_analysis import analyze_scenarios
from product_version import user_agent


class MarketScenarioService:
    """Collect public closed candles and publish SHADOW-only evidence."""

    def __init__(
        self,
        *,
        database: Path,
        status_file: Path,
        base_url: str,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        execution_symbols: Sequence[str],
        round_trip_cost_pct: Decimal,
        now_ms: Callable[[], int] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if round_trip_cost_pct < 0 or round_trip_cost_pct >= 1:
            raise ValueError("round-trip cost must be between zero and one")
        self.store = MarketScenarioStore(database)
        self.status_file = Path(status_file)
        self.base_url = base_url
        self.symbols = tuple(symbols)
        self.timeframes = tuple(timeframes)
        self.execution_symbols = tuple(execution_symbols)
        self.round_trip_cost_pct = Decimal(round_trip_cost_pct)
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent("market-scenario-shadow")})

    def run_once(self) -> dict[str, object]:
        """Analyze each configured scope independently and publish one status."""
        current_ms = self.now_ms()
        results: list[dict[str, object]] = []
        failures: list[dict[str, str]] = []
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                try:
                    bars = fetch_closed_klines(
                        self.session,
                        base_url=self.base_url,
                        symbol=symbol,
                        timeframe=timeframe,
                        now_ms=current_ms,
                    )
                    settled = self.store.settle(
                        symbol=symbol,
                        timeframe=timeframe,
                        bars=bars,
                        round_trip_cost_pct=self.round_trip_cost_pct,
                    )
                    analysis = analyze_scenarios(
                        symbol, timeframe, bars, now_ms=current_ms
                    )
                    snapshot_id = self.store.record(
                        analysis, created_at_ms=current_ms
                    )
                    results.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "snapshot_id": snapshot_id,
                        "settled_now": settled,
                        "analysis": analysis.as_dict(),
                        "statistics": self.store.statistics(
                            symbol=symbol, timeframe=timeframe
                        ),
                    })
                except (OSError, RuntimeError, ValueError, requests.RequestException) as exc:
                    failures.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "error_type": type(exc).__name__,
                    })
        payload: dict[str, object] = {
            "schema": "ladder-dragon-market-scenario-status-v1",
            "generated_at": datetime.fromtimestamp(
                current_ms / 1000, tz=timezone.utc
            ).isoformat(),
            "mode": "SHADOW",
            "apply_allowed": False,
            "can_change_orders": False,
            "market_data": "public_closed_klines",
            "round_trip_cost_pct": format(self.round_trip_cost_pct, "f"),
            "scope": prove_execution_scope_unchanged(
                self.execution_symbols, self.symbols
            ),
            "status": "PASS" if results and not failures else "DEGRADED",
            "results": results,
            "failures": failures,
        }
        self._write_status(payload)
        return payload

    def _write_status(self, payload: dict[str, object]) -> None:
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".market-scenario-", dir=self.status_file.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.status_file)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
