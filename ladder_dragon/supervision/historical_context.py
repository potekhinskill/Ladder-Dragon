# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect source-owned context asynchronously without execution authority.
"""One bounded observer for future L2 selection; never change a trading plan."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

import requests

from ladder_dragon.supervision.context_transport import HistoricalContextClient
from ladder_dragon.supervision.panic_observer import (
    read_panic_observation,
    refresh_panic_observation,
)
from ladder_dragon.strategy.prediction.context_journal import ContextJournal
from ladder_dragon.strategy.prediction.context_sources import (
    attest, context_from_sources, fee_source, filter_source, symbol_name,
)
from ladder_dragon.strategy.prediction.episode_semantics import (
    require_runtime_regime_contract, v23_evidence_semantics_contract,
)

SOURCE_ERRORS = (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError,
                 sqlite3.Error, requests.RequestException)


class HistoricalContextCollector:
    """One daemon task, no waiting queue, eight symbols, fixed source lifetimes."""

    def __init__(self, path: Path, *, public_get, signed_get, clock=None,
                 panic_run_dir: Path | None = None):
        self.path = Path(path)
        self.public_get, self.signed_get = public_get, signed_get
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.panic_run_dir = panic_run_dir
        self.session_id = uuid.uuid4().hex
        self.journal = None
        self.cache: dict[str, dict] = {}
        self.status: dict[str, dict] = {}
        self.last: dict[str, tuple[int, object]] = {}
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.busy = False
        self.job_signature = None
        self.invalidated_at: int | None = None

    def _source(self, kind: str, symbol: str) -> dict:
        now = self.clock()
        key = f"{symbol}:{kind}"
        cached = self.cache.get(key)
        # Refresh before expiry so normal polling does not create systematic gaps.
        if cached and cached["observed_at_ms"] <= now < cached["valid_until_ms"] - 60_000:
            return cached
        self.cache.pop(key, None)
        if kind == "filters":
            payload = self.public_get("/api/v3/exchangeInfo", {"symbol": symbol})
            source = filter_source(symbol, payload, self.clock())
        else:
            payload = self.signed_get("/api/v3/account/commission", {"symbol": symbol})
            source = fee_source(symbol, payload, self.clock())
        self.cache[key] = source
        return source

    def collect(self, symbol: str, runtime_source: dict | None, reason: str | None = None) -> dict:
        """Write only sanitized successful projections or an explicit evidence gap."""
        error_type = None
        sources = None
        try:
            # Refresh public PANIC state even when this first HALT observation
            # is blocked. The next supervisor cycle can consume fresh evidence.
            refresh_panic_observation(
                symbol,
                public_get=self.public_get,
                now_ms=self.clock(),
                run_dir=self.panic_run_dir,
            )
            if reason is None:
                sources = {"runtime": runtime_source, "filters": self._source("filters", symbol),
                           "fees": self._source("fees", symbol)}
                context_from_sources(sources, self.clock())
        except SOURCE_ERRORS as exc:
            sources = None
            reason = reason or "SOURCE_UNAVAILABLE"
            error_type = type(exc).__name__
        # Serialize the short local commit with runtime invalidation. Network
        # calls never hold this lock. An observed state change cannot be lost
        # behind an older job that finishes after the change.
        with self.lock:
            observed_at = self.clock()
            if self.invalidated_at is not None:
                observed_at = self.invalidated_at
                sources, reason = None, "OBSERVATION_SUPERSEDED"
            try:
                if self.journal is None:
                    self.journal = ContextJournal(self.path)
                result = self.journal.append(symbol=symbol, session_id=self.session_id,
                                             observed_at_ms=observed_at, sources=sources, reason=reason)
            except SOURCE_ERRORS as exc:
                result = {"status": "BLOCKED", "reason": "PERSISTENCE_UNAVAILABLE",
                          "observed_at_ms": self.clock()}
                error_type = type(exc).__name__
            result.update(mode="SHADOW", apply_allowed=False, error_type=error_type)
            self.status[symbol] = result
            self.busy = False
        return result

    def submit(self, symbol: str, *, arguments, environ: dict, regime: str,
               panic: bool | None, panic_hits: int | None) -> dict:
        """Capture the exact consumed runtime input before any asynchronous read."""
        symbol_name(symbol)
        now = self.clock()
        source, reason = None, None
        try:
            # This canonical validator is SOL-scoped; apply it to every context
            # symbol rather than silently admitting an unchecked classifier.
            require_runtime_regime_contract("SOLUSDT", arguments, environ)
            observation = read_panic_observation(
                symbol, now_ms=now, run_dir=self.panic_run_dir
            )
            if (
                type(panic) is not bool
                or type(panic_hits) is not int
                or observation is None
                or observation["on"] is not panic
                or observation["hits"] != panic_hits
            ):
                reason = "PANIC_UNAVAILABLE"
            else:
                source = attest("runtime", symbol, now, {
                    "classifier": v23_evidence_semantics_contract()["regime_classifier"],
                    "regime": regime, "panic": panic, "panic_hits": panic_hits,
                    "panic_source_fingerprint": observation["source_fingerprint"],
                    "panic_observed_at_ms": observation["updated_at_ms"],
                })
        except (AttributeError, ValueError, TypeError, ArithmeticError):
            reason = "CLASSIFIER_MISMATCH"
        signature = (symbol, regime, panic, panic_hits, reason)
        with self.lock:
            if symbol not in self.last and len(self.last) >= 8:
                return {"status": "BLOCKED", "reason": "SYMBOL_CAPACITY"}
            last = self.last.get(symbol)
            current = dict(self.status.get(symbol, {"status": "COLLECTING"}))
            if self.busy:
                if (self.job_signature[0] == symbol and self.job_signature != signature
                        and self.invalidated_at is None):
                    self.invalidated_at = now
                return current
            if last and 0 <= now - last[0] < 30_000 and signature == last[1]:
                return current
            self.last[symbol] = (now, signature)
            self.busy, self.job_signature, self.invalidated_at = True, signature, None
            self.thread = threading.Thread(target=self.collect, args=(symbol, source, reason),
                                           name="historical-context", daemon=True)
            try:
                self.thread.start()
            except RuntimeError:
                self.busy = False
                raise
            return current


_COLLECTOR: HistoricalContextCollector | None = None


def observe_runtime(runtime: dict, arguments, symbol: str, regime: str,
                    panic: bool | None, panic_hits: int | None) -> None:
    """Keep context available under HALT without coupling it to candidate plans."""
    global _COLLECTOR
    if os.getenv("BOT_HISTORICAL_CONTEXT_ENABLED", "0") != "1":
        return
    state = runtime["_AI_RUNTIME_STATUS"].setdefault("historical_context", {})
    try:
        symbols = os.getenv("BOT_HISTORICAL_CONTEXT_SYMBOLS", "SOLUSDT").split(",")
        if not 1 <= len(symbols) <= 8:
            raise ValueError("context symbol configuration invalid")
        symbols = [symbol_name(value.strip()) for value in symbols]
        if len(set(symbols)) != len(symbols):
            raise ValueError("context symbols duplicate")
        if symbol not in symbols:
            return
        store = runtime.get("_PREDICTION_SHADOW")
        if store is None:
            state[symbol] = {"status": "BLOCKED", "reason": "PREDICTION_STORE_UNAVAILABLE"}
            return
        path = Path(store.path).with_name("historical_context.sqlite3")
        if _COLLECTOR is None:
            market = runtime["TM"]
            client = HistoricalContextClient(base_url=market.BASE_URL,
                                             credentials=lambda: (market.API_KEY, market.API_SECRET))
            _COLLECTOR = HistoricalContextCollector(path, public_get=client.public_get, signed_get=client.signed_get)
        if _COLLECTOR.path != path:
            raise ValueError("context storage changed during process lifetime")
        state[symbol] = _COLLECTOR.submit(symbol, arguments=arguments, environ=os.environ,
                                        regime=regime, panic=panic, panic_hits=panic_hits)
    except SOURCE_ERRORS as exc:
        state[symbol] = {"status": "BLOCKED", "reason": "COLLECTOR_UNAVAILABLE", "error_type": type(exc).__name__}
