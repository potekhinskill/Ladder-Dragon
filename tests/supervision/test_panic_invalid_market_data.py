"""Invalid public prices cannot clear PANIC or renew its source timestamp."""

import pytest

from ladder_dragon.supervision import panic_observer as observer
from ladder_dragon.supervision import historical_context as context
from tests.supervision.test_panic_observer import klines, public
from tests.supervision.test_historical_context import captured, client


def active_state(tmp_path):
    for stamp in (1_000_000, 1_060_000, 1_120_000, 1_180_000):
        state = observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(klines(current="95", now_ms=stamp)),
            now_ms=stamp, run_dir=tmp_path)
    assert state["on"] is True and state["hits"] == 2
    return observer.panic_observer_path("SOLUSDT", run_dir=tmp_path)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e9999", "0", "-1", True, None, "private-sentinel"])
@pytest.mark.parametrize("field", [1, 2, 3, 4])
@pytest.mark.parametrize("row", [0, -2, -1])
def test_invalid_ohlc_preserves_active_state_bytes(tmp_path, value, field, row):
    path = active_state(tmp_path)
    before = path.read_bytes()
    payload = klines()
    payload[row][field] = value
    with pytest.raises(ValueError, match="PANIC observer price is invalid") as failure:
        observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(payload), now_ms=1_240_000, run_dir=tmp_path)
    assert "private-sentinel" not in str(failure.value)
    assert path.read_bytes() == before
    # Invalid input cannot renew freshness or leave a partial state file.
    assert observer.read_panic_observation("SOLUSDT", now_ms=1_300_001, run_dir=tmp_path) is None
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("indicator", ["ema_value", "atr_from_klines"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 0.0])
def test_invalid_derived_indicator_cannot_publish(tmp_path, monkeypatch, indicator, value):
    path = active_state(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(observer, indicator, lambda *_: value)
    with pytest.raises(ValueError, match="indicators are unavailable"):
        observer.refresh_panic_observation(
            "SOLUSDT", public_get=public(klines()), now_ms=1_240_000, run_dir=tmp_path)
    assert path.read_bytes() == before


def test_valid_recovery_after_invalid_price_retains_original_cooldown(tmp_path):
    active_state(tmp_path)
    with pytest.raises(ValueError):
        observer.refresh_panic_observation("SOLUSDT", public_get=public(klines(current="Infinity")),
                                          now_ms=1_240_000, run_dir=tmp_path)
    assert observer.read_panic_observation("SOLUSDT", now_ms=1_240_000, run_dir=tmp_path)["on"] is True
    recovered = observer.refresh_panic_observation("SOLUSDT", public_get=public(klines(now_ms=1_240_001)),
                                                   now_ms=1_240_001, run_dir=tmp_path)
    assert recovered["on"] is False and recovered["hits"] == 0
    assert recovered["since_ms"] == 1_060_000


def test_initial_invalid_observation_creates_no_state(tmp_path):
    with pytest.raises(ValueError, match="price is invalid"):
        observer.refresh_panic_observation("SOLUSDT", public_get=public(klines(current="NaN")),
                                          now_ms=1_000_000, run_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_validation_preserves_decimal_atr_inputs():
    payload = klines()
    for row in payload:
        row[2] = "100.0000000000000000000000001"
        row[3] = "99.9999999999999999999999999"
    expected = observer.atr_from_klines(payload, 14)
    assert expected > 0
    assert observer._indicators(payload)[2] == expected


@pytest.mark.parametrize("warmup", [False, True])
def test_invalid_market_data_blocks_collector_without_source_renewal(tmp_path, warmup):
    path = active_state(tmp_path)
    before = path.read_bytes()
    collector = context.HistoricalContextCollector(tmp_path / "context.sqlite3",
        public_get=public(klines(current="Infinity")), signed_get=client([]),
        clock=lambda: 1_240_000, panic_run_dir=tmp_path)
    result = collector.collect("SOLUSDT", None if warmup else captured(1_240_000),
                               "PANIC_WARMUP" if warmup else None)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_UNAVAILABLE"
    assert path.read_bytes() == before
    if warmup:
        assert not collector.path.exists()
    else:
        from tests.supervision.test_panic_consumed_context import rows
        assert rows(collector.path)[0]["sources"] == {}
