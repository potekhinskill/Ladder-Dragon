"""Prove PANIC source identity through runtime capture and journal publication."""

import json
import sqlite3
import threading

import pytest

from ladder_dragon.supervision import historical_context as context
from ladder_dragon.supervision import panic_observer as observer
from ladder_dragon.strategy.prediction.context_journal import export_context
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from tests.supervision.test_historical_context import arguments, captured, client, panic_capture


def rows(path):
    with sqlite3.connect(path) as connection:
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT payload FROM historical_context_records ORDER BY observed_at_ms")]


def test_transitions_use_consumed_source_and_leave_next_state_for_next_cycle(tmp_path, monkeypatch):
    now, trigger = [1_000], [False]
    monkeypatch.setenv("BOT_HISTORICAL_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(context.time, "time_ns", lambda: now[0] * 1_000_000)
    monkeypatch.setattr(observer, "panic_triggered", lambda *_: trigger[0])
    observer.refresh_panic_observation("SOLUSDT", public_get=client([]), now_ms=now[0], run_dir=tmp_path)
    collector = context.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client([]), signed_get=client([]),
        clock=lambda: now[0], panic_run_dir=tmp_path)
    consumed, refreshed = [], []
    for index in range(10):
        now[0] += 30_000
        trigger[0] = index < 2
        panic, hits, capture = context.capture_runtime_panic("SOLUSDT", None)
        consumed.append((panic, hits))
        collector.submit("SOLUSDT", arguments=arguments(), environ={}, regime="RANGE",
                         panic=panic, panic_hits=hits, panic_capture=capture)
        collector.thread.join(5)
        assert not collector.thread.is_alive()
        assert collector.status["SOLUSDT"]["status"] == "AVAILABLE"
        values = rows(collector.path)[-1]["sources"]["runtime"]["values"]
        assert (values["panic"], values["panic_hits"]) == (panic, hits)
        assert values["panic_observed_at_ms"] == capture["observation"]["updated_at_ms"]
        state = observer.read_panic_observation("SOLUSDT", now_ms=now[0], run_dir=tmp_path)
        refreshed.append((state["on"], state["hits"]))
    assert consumed[1:] == refreshed[:-1]
    assert consumed[:4] == [(False, 0), (False, 1), (True, 2), (True, 0)]
    assert consumed[-1] == (False, 0)
    assert collector.diagnostics.update([], now[0])["retained_failure_count"] == 0
    exported = export_context(collector.path, symbol="SOLUSDT",
        classifier_fingerprint=fingerprint(captured(1_000)["classifier"]),
        start_ms=32_000, end_ms=now[0] + 1_000, cutoff_ms=now[0] + 1_000)
    assert len(exported["context"]) == 10


@pytest.mark.parametrize("damage", [
    "missing", "fingerprint", "symbol", "hits", "flag", "stale", "future",
    "capture_future", "capture_before_source", "extra_secret",
])
def test_invalid_consumed_source_never_becomes_available(tmp_path, damage):
    value = captured(61_000)
    observation = value["panic_observation"]
    if damage == "missing":
        value.pop("panic_observation")
    elif damage == "fingerprint":
        observation["source_fingerprint"] = "0" * 64
    elif damage == "symbol":
        observation["symbol"] = "ETHUSDT"
    elif damage == "hits":
        observation["hits"] = 1
    elif damage == "flag":
        observation["on"] = True
    elif damage == "stale":
        observation["updated_at_ms"] = -100_000
    elif damage == "future":
        observation["updated_at_ms"] = 62_000
    elif damage == "capture_future":
        value["captured_at_ms"] = 62_000
    elif damage == "capture_before_source":
        value["captured_at_ms"] = 60_000
    else:
        observation["credential"] = "private-sentinel"
    collector = context.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client([]), signed_get=client([]),
        clock=lambda: 61_000, panic_run_dir=tmp_path)
    result = collector.collect("SOLUSDT", value)
    assert result["status"] == "BLOCKED"
    assert result["error_stage"] == "PANIC_MATCH"
    assert rows(collector.path)[0]["sources"] == {}
    assert "private-sentinel" not in repr(result)
    assert b"private-sentinel" not in collector.path.read_bytes()


def test_submission_detaches_source_before_background_io(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def slow(endpoint, params):
        entered.set()
        assert release.wait(5)
        return client([])(endpoint, params)
    collector = context.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=slow, signed_get=client([]),
        clock=lambda: 1_000, panic_run_dir=tmp_path)
    capture = panic_capture(1_000)
    collector.submit("SOLUSDT", arguments=arguments(), environ={}, regime="RANGE",
                     panic=False, panic_hits=0, panic_capture=capture)
    try:
        assert entered.wait(2)
        capture["observation"]["on"] = True
        capture["observation"]["source_fingerprint"] = "private-sentinel"
    finally:
        release.set()
        collector.thread.join(5)
    assert not collector.thread.is_alive()
    assert collector.status["SOLUSDT"]["status"] == "AVAILABLE"
    assert rows(collector.path)[0]["sources"]["runtime"]["values"]["panic"] is False
    assert b"private-sentinel" not in collector.path.read_bytes()


def test_disabled_capture_keeps_legacy_read_without_observer_io(monkeypatch):
    monkeypatch.delenv("BOT_HISTORICAL_CONTEXT_ENABLED", raising=False)
    def unexpected(*args, **kwargs):
        raise AssertionError("disabled observer must not read another source")
    monkeypatch.setattr(context, "read_panic_observation", unexpected)
    assert context.capture_runtime_panic("SOLUSDT", lambda _: (True, 2)) == (True, 2, None)


@pytest.mark.parametrize("capture", [None, {}, {"observation": panic_capture(1_000)["observation"]}])
def test_missing_capture_cannot_borrow_refreshed_source(tmp_path, capture):
    collector = context.HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=client([]), signed_get=client([]),
        clock=lambda: 1_000, panic_run_dir=tmp_path)
    collector.submit("SOLUSDT", arguments=arguments(), environ={}, regime="RANGE",
                     panic=False, panic_hits=0, panic_capture=capture)
    collector.thread.join(5)
    assert not collector.thread.is_alive()
    assert collector.status["SOLUSDT"]["status"] == "BLOCKED"
    assert collector.status["SOLUSDT"]["error_stage"] == "PANIC_MATCH"


def test_enabled_capture_reads_exactly_once_and_does_not_consult_legacy(monkeypatch):
    monkeypatch.setenv("BOT_HISTORICAL_CONTEXT_ENABLED", "1")
    calls = []
    def read(symbol, *, now_ms):
        calls.append((symbol, now_ms))
        return panic_capture(now_ms)["observation"]
    def legacy(_):
        raise AssertionError("a second read can consume a different state")
    monkeypatch.setattr(context, "read_panic_observation", read)
    panic, hits, capture = context.capture_runtime_panic("SOLUSDT", legacy)
    assert len(calls) == 1
    assert (panic, hits) == (False, 0)
    assert capture["captured_at_ms"] == calls[0][1]
