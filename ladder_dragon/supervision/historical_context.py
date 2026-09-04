# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect source-owned context asynchronously without execution authority.
"""One bounded observer for future L2 selection; never change a trading plan."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable
import uuid

import requests

from ladder_dragon.supervision.context_transport import HistoricalContextClient
from ladder_dragon.supervision.context_diagnostics import ContextDiagnostics, error_category
from ladder_dragon.supervision.panic_observer import (
    read_panic_observation, refresh_panic_observation, validate_panic_observation,
)
from ladder_dragon.strategy.prediction.context_journal import ContextJournal
from ladder_dragon.strategy.prediction.context_sources import (
    RUNTIME_TTL_MS,
    attest, context_from_sources, fee_schedule_source, fee_source,
    filter_source, symbol_name,
    validate_source,
)
from ladder_dragon.strategy.prediction.episode_semantics import (
    require_runtime_regime_contract, v23_evidence_semantics_contract,
)

SOURCE_ERRORS = (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError,
                 sqlite3.Error, requests.RequestException)
_FEE_SOURCE_UNSET = object()


def capture_runtime_panic(
    symbol: str, legacy_reader: Callable[[str], tuple[bool | None, int | None]],
) -> tuple[bool | None, int | None, dict | None]:
    """Read once at runtime consumption; keep a detached source for the journal."""
    if os.getenv("BOT_HISTORICAL_CONTEXT_ENABLED", "0") != "1":
        panic, hits = legacy_reader(symbol)
        return panic, hits, None
    now = time.time_ns() // 1_000_000
    try:
        observation = read_panic_observation(symbol, now_ms=now)
    except (OSError, TypeError, ValueError, OverflowError):
        observation = None
    if observation is None:
        return None, None, None
    return observation["on"], observation["hits"], {
        "captured_at_ms": now, "observation": observation,
    }


def fee_attestation_from_runtime_cache(
    symbol: str,
    cached: tuple[float, object] | None,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
) -> dict | None:
    """Project one fresh runtime commission cache entry without credentials."""
    if cached is None or len(cached) != 2:
        return None
    observed_at_ms = clock() - max(0, int((monotonic() - cached[0]) * 1000))
    schedule = cached[1]
    try:
        return fee_schedule_source(
            symbol,
            observed_at_ms,
            maker_buy=schedule.maker_buy,
            maker_sell=schedule.maker_sell,
            taker_buy=schedule.taker_buy,
            taker_sell=schedule.taker_sell,
        )
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
        return None


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
        self.diagnostics = ContextDiagnostics(self.path.with_suffix(".diagnostics.json"))

    def _diagnose(self, result: dict, events: list[dict]) -> None:
        """Keep diagnostic storage failure separate from authoritative evidence."""
        try:
            result["diagnostics"] = self.diagnostics.update(events, self.clock())
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            result["diagnostics"] = {"status": "UNAVAILABLE"}

    def _source(self, kind: str, symbol: str) -> dict:
        now = self.clock()
        key = f"{symbol}:{kind}"
        cached = self.cache.get(key)
        # A reused filter or fee attestation must outlive the new runtime
        # attestation. Otherwise the combined context expires before the next
        # observation and creates a deterministic gap every cache cycle.
        if (
            cached
            and cached["observed_at_ms"] <= now
            and cached["valid_until_ms"] - now >= RUNTIME_TTL_MS
        ):
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

    def collect(
        self,
        symbol: str,
        captured: dict | None,
        reason: str | None = None,
        fee_attestation: object = _FEE_SOURCE_UNSET,
    ) -> dict:
        """Write only sanitized successful projections or an explicit evidence gap."""
        error_type = None
        error_stage = None
        sources = None
        events = []
        def failure(stage: str, exc: BaseException) -> None:
            events.append({"observed_at_ms": self.clock(), "stage": stage,
                           "category": error_category(exc, stage)})
        if reason == "PANIC_WARMUP":
            try:
                refresh_panic_observation(
                    symbol,
                    public_get=self.public_get,
                    now_ms=self.clock(),
                    run_dir=self.panic_run_dir,
                )
                result = {
                    "status": "WARMING",
                    "reason": "PANIC_OBSERVER_PRIMED",
                }
            except SOURCE_ERRORS as exc:
                failure("PANIC_WARMUP", exc)
                result = {
                    "status": "BLOCKED",
                    "reason": "SOURCE_UNAVAILABLE",
                    "error_type": type(exc).__name__,
                }
            # A refreshed state was not consumed by this runtime cycle.
            # Prime the next cycle without writing false or unavailable evidence.
            result.update(mode="SHADOW", apply_allowed=False)
            self._diagnose(result, events)
            with self.lock:
                self.status[symbol] = result
                self.busy = False
            return result
        try:
            if reason is None:
                # Refresh only the next cycle's input. It is not the source
                # consumed by the current runtime decision.
                error_stage = "PANIC_REFRESH"
                refresh_panic_observation(
                    symbol,
                    public_get=self.public_get,
                    now_ms=self.clock(),
                    run_dir=self.panic_run_dir,
                )
                error_stage = "PANIC_MATCH"
                observed_at = self.clock()
                observation = validate_panic_observation(
                    symbol, captured.get("panic_observation") if captured else None,
                    now_ms=observed_at,
                )
                if (
                    captured is None
                    or observation is None
                    or type(captured["captured_at_ms"]) is not int
                    or not observation["updated_at_ms"] <= captured["captured_at_ms"] <= observed_at
                    or observed_at - captured["captured_at_ms"] >= 120_000
                    or observation["on"] is not captured["panic"]
                    or observation["hits"] != captured["panic_hits"]
                ):
                    raise ValueError("PANIC observation differs from runtime")
                error_stage = "RUNTIME_SOURCE"
                runtime_source = attest("runtime", symbol, observed_at, {
                    "classifier": captured["classifier"],
                    "regime": captured["regime"],
                    "panic": captured["panic"],
                    "panic_hits": captured["panic_hits"],
                    "panic_source_fingerprint": observation["source_fingerprint"],
                    "panic_observed_at_ms": observation["updated_at_ms"],
                })
                sources = {"runtime": runtime_source}
                error_stage = None
                try:
                    sources["filters"] = self._source("filters", symbol)
                except SOURCE_ERRORS:
                    error_stage = "FILTER_SOURCE"
                    raise
                try:
                    if fee_attestation is _FEE_SOURCE_UNSET:
                        sources["fees"] = self._source("fees", symbol)
                    else:
                        validate_source("fees", fee_attestation)
                        sources["fees"] = fee_attestation
                except SOURCE_ERRORS:
                    error_stage = "FEE_SOURCE"
                    raise
                try:
                    context_from_sources(sources, self.clock())
                except SOURCE_ERRORS:
                    error_stage = "SOURCE_BUNDLE"
                    raise
        except SOURCE_ERRORS as exc:
            failure(error_stage or "CAPTURE", exc)
            sources = None
            reason = reason or "SOURCE_UNAVAILABLE"
            error_type = type(exc).__name__
        # Finish diagnostic I/O before the authoritative commit. A submission
        # during diagnostics can still invalidate this uncommitted observation.
        diagnostics = {}
        self._diagnose(diagnostics, events)
        persistence_failed = False
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
                persistence_failed = True
                failure("PERSISTENCE", exc)
                result = {"status": "BLOCKED", "reason": "PERSISTENCE_UNAVAILABLE",
                          "observed_at_ms": self.clock()}
                error_type = type(exc).__name__
            result.update(
                mode="SHADOW",
                apply_allowed=False,
                error_type=error_type,
                error_stage=error_stage,
                diagnostics=diagnostics["diagnostics"],
            )
            if not persistence_failed:
                # Commit, publication, and writer release share one boundary.
                self.status[symbol] = result
                self.busy = False
                return result
        # A failed commit cannot publish AVAILABLE. Retain only the new failure;
        # previous source failures were already recorded before the commit.
        self._diagnose(result, events[-1:])
        with self.lock:
            self.status[symbol] = result
            self.busy = False
        return result

    def submit(self, symbol: str, *, arguments, environ: dict, regime: str,
               panic: bool | None, panic_hits: int | None,
               panic_capture: dict | None = None,
               fee_attestation: object = _FEE_SOURCE_UNSET) -> dict:
        """Capture the exact consumed runtime input before any asynchronous read."""
        symbol_name(symbol)
        now = self.clock()
        captured, reason = None, None
        try:
            # This canonical validator is SOL-scoped; apply it to every context
            # symbol rather than silently admitting an unchecked classifier.
            require_runtime_regime_contract("SOLUSDT", arguments, environ)
            if (
                type(panic) is not bool
                or type(panic_hits) is not int
            ):
                reason = "PANIC_WARMUP"
            else:
                capture = panic_capture if isinstance(panic_capture, dict) else {}
                captured = {
                    "classifier": v23_evidence_semantics_contract()["regime_classifier"],
                    "captured_at_ms": capture.get("captured_at_ms"),
                    "panic_observation": deepcopy(capture.get("observation")),
                    "regime": regime,
                    "panic": panic,
                    "panic_hits": panic_hits,
                }
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
            self.thread = threading.Thread(
                target=self.collect,
                args=(symbol, captured, reason, fee_attestation),
                                           name="historical-context", daemon=True)
            try:
                self.thread.start()
            except RuntimeError:
                self.busy = False
                raise
            return current


_COLLECTOR: HistoricalContextCollector | None = None


def observe_runtime(runtime: dict, arguments, symbol: str, regime: str,
                    panic: bool | None, panic_hits: int | None,
                    panic_capture: dict | None = None,
                    fee_attestation: object = _FEE_SOURCE_UNSET) -> None:
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
                                        regime=regime, panic=panic, panic_hits=panic_hits,
                                        panic_capture=panic_capture,
                                        fee_attestation=fee_attestation)
    except SOURCE_ERRORS as exc:
        state[symbol] = {"status": "BLOCKED", "reason": "COLLECTOR_UNAVAILABLE", "error_type": type(exc).__name__}
