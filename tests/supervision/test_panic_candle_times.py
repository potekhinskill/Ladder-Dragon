"""Source chronology must be valid before public PANIC state can change."""

import pytest

from ladder_dragon.supervision import panic_observer as observer
from ladder_dragon.supervision.historical_context import HistoricalContextCollector
from tests.supervision.test_historical_context import captured, client
from tests.supervision.test_panic_observer import klines, public


NOW = 1_788_534_000_000


def active_state(tmp_path):
    for stamp in range(NOW - 240_000, NOW, 60_000):
        state = observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(klines(current="95", now_ms=stamp)),
            now_ms=stamp, run_dir=tmp_path)
    assert state["on"] is True
    return observer.panic_observer_path("SOLUSDT", run_dir=tmp_path)


@pytest.mark.parametrize("damage", ["stale", "future", "reverse", "duplicate", "gap", "alignment", "close"])
def test_bad_chronology_cannot_clear_or_renew_active_panic(tmp_path, damage):
    path = active_state(tmp_path)
    before = path.read_bytes()
    payload = klines(now_ms=NOW)
    if damage in {"stale", "future"}:
        payload = klines(now_ms=NOW + (-86_400_000 if damage == "stale" else 60_000))
    elif damage == "reverse":
        payload.reverse()
    elif damage == "duplicate":
        payload[3] = payload[2][:]
    elif damage == "gap":
        del payload[3]
    elif damage == "alignment":
        for row in payload:
            row[0] += 1
            row[6] += 1
    else:
        payload[3][6] += 1
    with pytest.raises(ValueError, match="PANIC observer candle"):
        observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(payload), now_ms=NOW, run_dir=tmp_path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    assert observer.read_panic_observation("SOLUSDT", now_ms=NOW + 60_001, run_dir=tmp_path) is None
    recovered = observer.refresh_panic_observation(
        "SOLUSDT", public_get=public(klines(now_ms=NOW)), now_ms=NOW, run_dir=tmp_path)
    assert recovered["on"] is False
    assert recovered["since_ms"] == NOW - 180_000


@pytest.mark.parametrize("field", [0, 6])
@pytest.mark.parametrize("value", [True, None, "private-sentinel", 1.0, float("inf")])
def test_timestamp_types_fail_closed_without_source_leak(tmp_path, field, value):
    payload = klines(now_ms=NOW)
    payload[0][field] = value
    with pytest.raises(ValueError, match="chronology is invalid") as error:
        observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(payload), now_ms=NOW, run_dir=tmp_path)
    assert "private-sentinel" not in str(error.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("age,valid", [(-5001, False), (-5000, True), (0, True), (59999, True), (64999, True), (65000, False)])
def test_forming_candle_freshness_boundaries(tmp_path, age, valid):
    payload = klines(now_ms=NOW)
    if valid:
        result = observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(payload), now_ms=NOW + age, run_dir=tmp_path)
        assert result["updated_at_ms"] == NOW + age
    else:
        with pytest.raises(ValueError, match="freshness is invalid"):
            observer.refresh_panic_observation(
                "SOLUSDT", public_get=public(payload), now_ms=NOW + age, run_dir=tmp_path)
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("elapsed", [-1, 65000, 120000])
def test_arrival_clock_rejects_delayed_or_reversed_response(tmp_path, elapsed):
    path = active_state(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(klines(now_ms=NOW)), now_ms=NOW,
            clock=lambda: NOW + elapsed, run_dir=tmp_path)
    assert path.read_bytes() == before


def test_valid_response_uses_arrival_time(tmp_path):
    result = observer.refresh_panic_observation(
        "SOLUSDT", public_get=public(klines(now_ms=NOW)), now_ms=NOW - 1000,
        clock=lambda: NOW, run_dir=tmp_path)
    assert result["updated_at_ms"] == NOW


@pytest.mark.parametrize("warmup", [False, True])
@pytest.mark.parametrize("delayed", [False, True])
def test_stale_source_blocks_real_collector_publication(tmp_path, warmup, delayed):
    path = active_state(tmp_path)
    before = path.read_bytes()
    now = [NOW]
    def get(endpoint, params):
        if delayed:
            now[0] += 65_000
        return public(klines(now_ms=NOW if delayed else NOW - 86_400_000))(endpoint, params)
    collector = HistoricalContextCollector(
        tmp_path / "context.sqlite3", public_get=get,
        signed_get=client([]), clock=lambda: now[0], panic_run_dir=tmp_path)
    result = collector.collect("SOLUSDT", None if warmup else captured(NOW),
                               "PANIC_WARMUP" if warmup else None)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_UNAVAILABLE"
    assert path.read_bytes() == before
    if warmup:
        assert not collector.path.exists()
    else:
        from tests.supervision.test_panic_consumed_context import rows
        assert rows(collector.path)[0]["sources"] == {}
