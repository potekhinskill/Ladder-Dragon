from pathlib import Path
import threading
from types import SimpleNamespace
from decimal import Decimal

import requests
import pytest

from ladder_dragon.supervision import historical_context as module
from ladder_dragon.strategy.prediction.context_journal import export_context
from ladder_dragon.strategy.prediction.episode_semantics import v23_evidence_semantics_contract
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.context_sources import fee_schedule_source
from ladder_dragon.supervision.panic_observer import (
    panic_observer_fingerprint, refresh_panic_observation,
)


def arguments():
    return SimpleNamespace(dir_mode="auto", dir_interval="30m", dir_eps="0.0005",
                           dir_slope_min="0.0002", dir_adx_min="16", dir_confirm_bars=3)


def captured(now):
    return {
        "classifier": v23_evidence_semantics_contract()["regime_classifier"],
        "captured_at_ms": now,
        "regime": "RANGE",
        "panic": False,
        "panic_hits": 0,
        "panic_observation": panic_capture(now)["observation"],
    }


def panic_capture(now):
    return {"captured_at_ms": now, "observation": {
        "schema_version": 1, "symbol": "SOLUSDT", "on": False, "hits": 0,
        "since_ms": 0, "last_trigger_ms": 0, "updated_at_ms": now,
        "source_fingerprint": panic_observer_fingerprint(),
    }}


def klines(now_ms=1000):
    base = (now_ms // 60_000 - 119) * 60_000
    return [
        [base + index * 60_000, "100", "101", "99", "100", "1",
         base + index * 60_000 + 59_999]
        for index in range(120)
    ]


def client(calls, clock=lambda: 1000):
    def get(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "/api/v3/klines":
            return klines(clock())
        if endpoint == "/api/v3/exchangeInfo":
            return {"symbols": [{"symbol": "SOLUSDT", "status": "TRADING", "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "NOTIONAL", "minNotional": "5"},
            ]}]}
        assert endpoint == "/api/v3/account/commission"
        return {"symbol": "SOLUSDT", **{name: {"maker": "0.001", "taker": "0.001", "buyer": "0", "seller": "0"}
                                        for name in ("standardCommission", "taxCommission", "specialCommission")}}
    return get


def test_get_only_collection_caches_without_renewing_source_time(tmp_path):
    calls, now = [], [1000]
    collector = module.HistoricalContextCollector(tmp_path / "context.sqlite3", public_get=client(calls, lambda: now[0]),
                                                 signed_get=client(calls), clock=lambda: now[0],
                                                 panic_run_dir=tmp_path)
    assert collector.collect("SOLUSDT", captured(1000))["status"] == "AVAILABLE"
    now[0] = 61_000
    assert collector.collect("SOLUSDT", captured(61_000))["status"] == "AVAILABLE"
    assert len(calls) == 4
    assert collector.cache["SOLUSDT:fees"]["observed_at_ms"] == 1000
    now[0] = 121_001
    assert collector.collect("SOLUSDT", captured(121_001))["status"] == "AVAILABLE"
    assert len(calls) == 7
    assert collector.cache["SOLUSDT:fees"]["observed_at_ms"] == 121_001


def test_runtime_fee_attestation_avoids_a_second_signed_request(tmp_path):
    calls, now = [], [1_000]

    def signed_get(*_args):
        raise AssertionError("the collector must reuse the runtime fee source")

    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3",
        public_get=client(calls),
        signed_get=signed_get,
        clock=lambda: now[0],
        panic_run_dir=tmp_path,
    )
    fee_attestation = fee_schedule_source(
        "SOLUSDT",
        now[0],
        maker_buy="0.001",
        maker_sell="0.001",
        taker_buy="0.001",
        taker_sell="0.001",
    )

    result = collector.collect(
        "SOLUSDT",
        captured(now[0]),
        fee_attestation=fee_attestation,
    )

    assert result["status"] == "AVAILABLE"
    assert [endpoint for endpoint, _ in calls].count(
        "/api/v3/exchangeInfo"
    ) == 1
    assert all(endpoint != "/api/v3/account/commission" for endpoint, _ in calls)


def test_runtime_cache_projection_preserves_original_observation_time():
    schedule = SimpleNamespace(
        maker_buy=Decimal("0.001"),
        maker_sell=Decimal("0.002"),
        taker_buy=Decimal("0.003"),
        taker_sell=Decimal("0.004"),
    )

    result = module.fee_attestation_from_runtime_cache(
        "SOLUSDT",
        (880.0, schedule),
        monotonic=lambda: 1_000.0,
        clock=lambda: 1_000_000,
    )

    assert result["observed_at_ms"] == 880_000
    assert result["values"]["taker_sell_fee_pct"] == "0.004"


def test_invalid_runtime_fee_attestation_reports_a_safe_stage(tmp_path):
    calls = []
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3",
        public_get=client(calls),
        signed_get=client(calls),
        clock=lambda: 1_000,
        panic_run_dir=tmp_path,
    )

    result = collector.collect(
        "SOLUSDT",
        captured(1_000),
        fee_attestation={"damaged": True},
    )

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_UNAVAILABLE"
    assert result["error_type"] == "ValueError"
    assert result["error_stage"] == "FEE_SOURCE"


def test_missing_runtime_fee_attestation_does_not_retry_signed_get(tmp_path):
    calls = []

    def signed_get(*_args):
        raise AssertionError("missing runtime fees must remain fail-closed")

    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3",
        public_get=client(calls),
        signed_get=signed_get,
        clock=lambda: 1_000,
        panic_run_dir=tmp_path,
    )

    result = collector.collect(
        "SOLUSDT",
        captured(1_000),
        fee_attestation=None,
    )

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_UNAVAILABLE"
    assert result["error_stage"] == "FEE_SOURCE"


def test_cached_sources_cover_a_six_hour_export_without_periodic_gaps(tmp_path):
    calls, now = [], [1_000]
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3",
        public_get=client(calls, lambda: now[0]),
        signed_get=client(calls),
        clock=lambda: now[0],
        panic_run_dir=tmp_path,
    )
    classifier = fingerprint(
        v23_evidence_semantics_contract()["regime_classifier"]
    )
    end_ms = 6 * 60 * 60_000
    while now[0] <= end_ms + 31_000:
        refresh_panic_observation(
            "SOLUSDT",
            public_get=client(calls, lambda: now[0]),
            now_ms=now[0],
            run_dir=tmp_path,
        )
        collector.collect("SOLUSDT", captured(now[0]))
        now[0] += 30_000

    exported = export_context(
        collector.path,
        symbol="SOLUSDT",
        classifier_fingerprint=classifier,
        start_ms=31_000,
        end_ms=end_ms,
        cutoff_ms=end_ms,
    )

    assert exported["start_ms"] == 31_000
    assert exported["end_ms"] == end_ms
    assert len(exported["context"]) > 700


def test_failure_and_missing_panic_are_explicit_and_secret_safe(tmp_path):
    def failing(*args):
        raise requests.RequestException("signed-url-do-not-disclose")
    collector = module.HistoricalContextCollector(tmp_path / "context.sqlite3", public_get=failing,
                                                 signed_get=failing, clock=lambda: 1000,
                                                 panic_run_dir=tmp_path)
    result = collector.collect("SOLUSDT", captured(1000))
    assert result["status"] == "BLOCKED" and result["reason"] == "SOURCE_UNAVAILABLE"
    assert "signed-url" not in repr(result)
    assert b"signed-url" not in collector.path.read_bytes()
    collector.clock = lambda: 2000
    result = collector.collect("SOLUSDT", None, "PANIC_UNAVAILABLE")
    assert result["reason"] == "PANIC_UNAVAILABLE"


def test_submission_primes_missing_panic_without_journal_gap(tmp_path):
    calls, now = [], [1000]
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3",
        public_get=client(calls),
        signed_get=client(calls),
        clock=lambda: now[0],
        panic_run_dir=tmp_path,
    )

    collector.submit(
        "SOLUSDT",
        arguments=arguments(),
        environ={},
        regime="RANGE",
        panic=None,
        panic_hits=None,
    )
    collector.thread.join(5)

    assert collector.status["SOLUSDT"]["status"] == "WARMING"
    assert any(endpoint == "/api/v3/klines" for endpoint, _ in calls)
    assert not collector.path.exists()

    now[0] = 31_000
    collector.submit(
        "SOLUSDT",
        arguments=arguments(),
        environ={},
        regime="RANGE",
        panic=False,
        panic_hits=0,
        panic_capture=panic_capture(now[0]),
    )
    collector.thread.join(5)

    assert collector.status["SOLUSDT"]["status"] == "AVAILABLE"
    assert collector.path.exists()


@pytest.mark.parametrize("other_symbol", [False, True])
def test_submission_never_waits_or_queues_more_work(tmp_path, other_symbol):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(endpoint, params):
        entered.set()
        assert release.wait(5)
        return client(calls)(endpoint, params)
    collector = module.HistoricalContextCollector(tmp_path / "context.sqlite3", public_get=slow,
                                                 signed_get=client(calls), clock=lambda: 1000,
                                                 panic_run_dir=tmp_path)
    refresh_panic_observation(
        "SOLUSDT", public_get=client(calls), now_ms=1000, run_dir=tmp_path
    )
    calls.clear()
    try:
        collector.submit("SOLUSDT", arguments=arguments(), environ={}, regime="RANGE", panic=False, panic_hits=0, panic_capture=panic_capture(1000))
        assert entered.wait(2)
        first = collector.thread
        collector.submit("ETHUSDT" if other_symbol else "SOLUSDT", arguments=arguments(), environ={},
                         regime="TREND_UP", panic=False, panic_hits=0, panic_capture=panic_capture(1000))
        assert collector.thread is first
    finally:
        release.set()
        collector.thread.join(5)
    assert not collector.thread.is_alive()
    assert len(calls) == 3
    assert collector.status["SOLUSDT"]["reason"] == (None if other_symbol else "OBSERVATION_SUPERSEDED")


def test_disabled_observer_has_no_side_effects(monkeypatch):
    monkeypatch.delenv("BOT_HISTORICAL_CONTEXT_ENABLED", raising=False)
    monkeypatch.setattr(module, "_COLLECTOR", None)
    module.observe_runtime({}, None, "SOLUSDT", "RANGE", False, 0)
    assert module._COLLECTOR is None


def test_runtime_wiring_respects_scope_and_preserves_halt(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "_COLLECTOR", None)
    monkeypatch.setenv("BOT_HISTORICAL_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("BOT_HISTORICAL_CONTEXT_SYMBOLS", "SOLUSDT")
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(module, "HistoricalContextClient", lambda **_: SimpleNamespace(
        public_get=client(calls, lambda: int(module.time.time() * 1000)), signed_get=client(calls)))
    runtime = {"_AI_RUNTIME_STATUS": {"risk": {"halted": True}},
               "_PREDICTION_SHADOW": SimpleNamespace(path=tmp_path / "prediction.sqlite3"),
               "TM": SimpleNamespace(BASE_URL="https://api.binance.com")}
    refresh_panic_observation(
        "SOLUSDT", public_get=client(calls, lambda: int(module.time.time() * 1000)), now_ms=int(module.time.time() * 1000),
        run_dir=tmp_path,
    )
    calls.clear()
    for symbol in ("ETHUSDT", "BTCUSDT"):
        module.observe_runtime(runtime, arguments(), symbol, "RANGE", False, 0)
    assert module._COLLECTOR is None and not calls
    panic, hits, source = module.capture_runtime_panic("SOLUSDT", None)
    module.observe_runtime(runtime, arguments(), "SOLUSDT", "RANGE", panic, hits, panic_capture=source)
    collector = module._COLLECTOR
    collector.thread.join(5)
    assert not collector.thread.is_alive()
    assert collector.status["SOLUSDT"]["status"] == "AVAILABLE"
    assert runtime["_AI_RUNTIME_STATUS"]["risk"] == {"halted": True}
    source = Path("ladder_dragon/supervision/runtime.py").read_text()
    assert source.index(
        "commission_schedule = _commission_schedule(symbol)"
    ) < source.index("historical_context.observe_runtime(")
    assert source.index("historical_context.observe_runtime(") < source.index("    # 4) Exchange filters")


def test_delayed_sources_cannot_backdate_or_extend_runtime(tmp_path):
    now, calls = [1000], []
    def delayed(endpoint, params):
        now[0] = 200000
        return client(calls)(endpoint, params)
    collector = module.HistoricalContextCollector(tmp_path / "context.sqlite3", public_get=delayed,
                                                 signed_get=client(calls), clock=lambda: now[0],
                                                 panic_run_dir=tmp_path)
    assert collector.collect("SOLUSDT", captured(1000))["status"] == "BLOCKED"


def test_evidence_from_collector_reaches_read_only_export(tmp_path):
    calls = []
    collector = module.HistoricalContextCollector(tmp_path / "context.sqlite3", public_get=client(calls),
                                                 signed_get=client(calls), clock=lambda: 1000,
                                                 panic_run_dir=tmp_path)
    collector.collect("SOLUSDT", captured(1000))
    result = export_context(collector.path, symbol="SOLUSDT",
                            classifier_fingerprint=fingerprint(v23_evidence_semantics_contract()["regime_classifier"]),
                            start_ms=2000, end_ms=10000, cutoff_ms=10000)
    assert result["context"][0]["regime"] == "RANGE"
    assert result["context"][0]["observed_at_ms"] == 1000


def test_service_enables_only_observer_and_uses_existing_writable_storage():
    source = Path("deploy/mybot.service").read_text()
    assert "Environment=BOT_HISTORICAL_CONTEXT_ENABLED=1" in source
    assert "Environment=BOT_HISTORICAL_CONTEXT_SYMBOLS=SOLUSDT" in source
    assert "ReadWritePaths=/home/bot/apps/binance_bot/db" in source


@pytest.mark.parametrize("endpoint,stage", [
    ("/api/v3/klines", "PANIC_REFRESH"),
    ("/api/v3/exchangeInfo", "FILTER_SOURCE"),
    ("/api/v3/account/commission", "FEE_SOURCE"),
])
def test_failure_details_survive_success(tmp_path, endpoint, stage):
    now, calls, failed = [1_000], [], [True]
    def get(path, params):
        if failed[0] and path == endpoint:
            raise requests.Timeout("private-sentinel")
        return client(calls)(path, params)
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=get, signed_get=get,
        clock=lambda: now[0], panic_run_dir=tmp_path)
    result = collector.collect("SOLUSDT", captured(now[0]))
    assert result["status"] == "BLOCKED"
    details = result["diagnostics"]
    assert details["last_failure"] == {
        "observed_at_ms": 1_000, "stage": stage, "category": "TIMEOUT"}
    failed[0], now[0] = False, 61_000
    result = collector.collect("SOLUSDT", captured(now[0]))
    assert result["status"] == "AVAILABLE"
    assert result["diagnostics"] == details
    assert b"private-sentinel" not in collector.diagnostics.path.read_bytes()
    assert "private-sentinel" not in repr(result)
    # Diagnostic recovery never rewrites the original evidence gap.
    with pytest.raises(ValueError):
        export_context(collector.path, symbol="SOLUSDT",
            classifier_fingerprint=fingerprint(v23_evidence_semantics_contract()["regime_classifier"]),
            start_ms=2_000, end_ms=70_000, cutoff_ms=70_000)


def test_diagnostic_failure_does_not_change_evidence(tmp_path, monkeypatch):
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client([]), signed_get=client([]),
        clock=lambda: 1_000, panic_run_dir=tmp_path)
    def fail(*args):
        raise OSError("private-sentinel")
    monkeypatch.setattr(collector.diagnostics, "update", fail)
    result = collector.collect("SOLUSDT", captured(1_000))
    assert result["status"] == "AVAILABLE"
    assert result["diagnostics"] == {"status": "UNAVAILABLE"}
    assert "private-sentinel" not in repr(result)
    collector.public_get = fail
    result = collector.collect("SOLUSDT", captured(1_000))
    assert result["status"] == "BLOCKED"
    assert result["diagnostics"]["status"] == "UNAVAILABLE"


def test_panic_mismatch_and_persistence_remain_distinct(tmp_path, monkeypatch):
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client([]), signed_get=client([]),
        clock=lambda: 1_000, panic_run_dir=tmp_path)
    state = captured(1_000)
    state["panic"] = True
    result = collector.collect("SOLUSDT", state)
    assert result["diagnostics"]["last_failure"]["category"] == "STATE_MISMATCH"
    def fail(**kwargs):
        raise OSError("private-sentinel")
    monkeypatch.setattr(collector.journal, "append", fail)
    result = collector.collect("SOLUSDT", state)
    assert result["status"] == "BLOCKED"
    assert result["diagnostics"]["category_counts"] == {"STATE_MISMATCH": 2, "PERSISTENCE": 1}


def test_warmup_failure_is_retained_without_false_evidence(tmp_path):
    def fail(*args):
        raise requests.Timeout("private-sentinel")
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=fail, signed_get=fail,
        clock=lambda: 1_000, panic_run_dir=tmp_path)
    result = collector.collect("SOLUSDT", None, "PANIC_WARMUP")
    assert result["diagnostics"]["last_failure"]["stage"] == "PANIC_WARMUP"
    assert not collector.path.exists()


@pytest.mark.parametrize("warmup", [False, True])
def test_slow_diagnostics_do_not_hold_submission_lock(tmp_path, monkeypatch, warmup):
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client([]), signed_get=client([]),
        clock=lambda: 1_000, panic_run_dir=tmp_path)
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(5)
        return {"status": "AVAILABLE"}
    monkeypatch.setattr(collector.diagnostics, "update", slow)
    kwargs = dict(arguments=arguments(), environ={}, regime="RANGE",
                  panic=None if warmup else False, panic_hits=None if warmup else 0,
                  panic_capture=None if warmup else panic_capture(1000))
    collector.submit("SOLUSDT", **kwargs)
    writer = collector.thread
    def submit():
        collector.submit("SOLUSDT", **kwargs)
        returned.set()
    caller = threading.Thread(target=submit)
    try:
        assert entered.wait(2)
        caller.start()
        assert returned.wait(1), "diagnostic I/O blocked the supervisor"
        assert collector.thread is writer
        assert collector.busy
    finally:
        release.set()
        writer.join(5)
        if caller.ident is not None:
            caller.join(5)
    assert not writer.is_alive()
    assert not collector.busy


@pytest.mark.parametrize("changed", ["regime", "panic", "panic_hits"])
@pytest.mark.parametrize("storage_fails", [False, True])
def test_change_during_diagnostics_blocks_export(tmp_path, monkeypatch, changed, storage_fails):
    now = [1_000]
    collector = module.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client([]), signed_get=client([]),
        clock=lambda: now[0], panic_run_dir=tmp_path)
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(5)
        if storage_fails:
            raise OSError("private-sentinel")
        return {"status": "AVAILABLE"}
    monkeypatch.setattr(collector.diagnostics, "update", slow)
    kwargs = dict(arguments=arguments(), environ={}, regime="RANGE", panic=False, panic_hits=0,
                  panic_capture=panic_capture(1000))
    collector.submit("SOLUSDT", **kwargs)
    writer = collector.thread
    try:
        assert entered.wait(2)
        now[0] = 61_000
        kwargs[changed] = {"regime": "TREND_DOWN", "panic": True, "panic_hits": 1}[changed]
        collector.submit("SOLUSDT", **kwargs)
        assert collector.thread is writer
        assert collector.invalidated_at == 61_000
    finally:
        release.set()
        writer.join(5)
    assert not writer.is_alive()
    assert not collector.busy
    result = collector.status["SOLUSDT"]
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "OBSERVATION_SUPERSEDED"
    assert result["observed_at_ms"] == 61_000
    assert "private-sentinel" not in repr(result)
    with pytest.raises(ValueError, match="unavailable evidence"):
        export_context(collector.path, symbol="SOLUSDT",
            classifier_fingerprint=fingerprint(v23_evidence_semantics_contract()["regime_classifier"]),
            start_ms=62_000, end_ms=70_000, cutoff_ms=70_000)
