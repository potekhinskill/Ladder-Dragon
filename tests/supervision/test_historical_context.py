from pathlib import Path
import threading
from types import SimpleNamespace

import requests
import pytest

from ladder_dragon.supervision import historical_context as module
from ladder_dragon.strategy.prediction.context_journal import export_context
from ladder_dragon.strategy.prediction.episode_semantics import v23_evidence_semantics_contract
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.supervision.panic_observer import (
    refresh_panic_observation,
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
    }


def klines():
    return [
        [index * 60_000, "100", "101", "99", "100", "1",
         index * 60_000 + 59_999]
        for index in range(120)
    ]


def client(calls):
    def get(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "/api/v3/klines":
            return klines()
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
    collector = module.HistoricalContextCollector(tmp_path / "context.sqlite3", public_get=client(calls),
                                                 signed_get=client(calls), clock=lambda: now[0],
                                                 panic_run_dir=tmp_path)
    assert collector.collect("SOLUSDT", captured(1000))["status"] == "AVAILABLE"
    now[0] = 61_000
    assert collector.collect("SOLUSDT", captured(61_000))["status"] == "AVAILABLE"
    assert len(calls) == 4
    assert collector.cache["SOLUSDT:fees"]["observed_at_ms"] == 1000
    now[0] = 242_000
    assert collector.collect("SOLUSDT", captured(242_000))["status"] == "AVAILABLE"
    assert len(calls) == 7


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
        collector.submit("SOLUSDT", arguments=arguments(), environ={}, regime="RANGE", panic=False, panic_hits=0)
        assert entered.wait(2)
        first = collector.thread
        collector.submit("ETHUSDT" if other_symbol else "SOLUSDT", arguments=arguments(), environ={},
                         regime="TREND_UP", panic=False, panic_hits=0)
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
        public_get=client(calls), signed_get=client(calls)))
    runtime = {"_AI_RUNTIME_STATUS": {"risk": {"halted": True}},
               "_PREDICTION_SHADOW": SimpleNamespace(path=tmp_path / "prediction.sqlite3"),
               "TM": SimpleNamespace(BASE_URL="https://api.binance.com")}
    refresh_panic_observation(
        "SOLUSDT", public_get=client(calls), now_ms=int(module.time.time() * 1000),
        run_dir=tmp_path,
    )
    calls.clear()
    for symbol in ("ETHUSDT", "BTCUSDT"):
        module.observe_runtime(runtime, arguments(), symbol, "RANGE", False, 0)
    assert module._COLLECTOR is None and not calls
    module.observe_runtime(runtime, arguments(), "SOLUSDT", "RANGE", False, 0)
    collector = module._COLLECTOR
    collector.thread.join(5)
    assert not collector.thread.is_alive()
    assert collector.status["SOLUSDT"]["status"] == "AVAILABLE"
    assert runtime["_AI_RUNTIME_STATUS"]["risk"] == {"halted": True}
    source = Path("ladder_dragon/supervision/runtime.py").read_text()
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
