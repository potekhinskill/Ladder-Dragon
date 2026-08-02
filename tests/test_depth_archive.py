import json

from ladder_dragon.strategy.depth_archive import record_public_depth, stream_url
from ladder_dragon.strategy.market_replay import (
    archive_sha256,
    calibrate_market_events,
    load_jsonl_archive,
)


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "lastUpdateId": 100,
            "bids": [["75.00", "10"]],
            "asks": [["75.02", "10"]],
        }


class FakeSession:
    def get(self, url, params, timeout):
        assert url.startswith("https://data-api.binance.vision/")
        assert params == {"symbol": "SOLUSDT", "limit": 1000}
        assert timeout == 15
        return FakeResponse()


class FakeConnection:
    def __init__(self):
        self.frames = iter([
            {"data": {
                "e": "depthUpdate", "E": 1_010, "s": "SOLUSDT",
                "U": 101, "u": 101, "b": [["75.00", "11"]], "a": [],
            }},
            {"data": {
                "e": "aggTrade", "E": 1_020, "s": "SOLUSDT",
                "a": 1234, "p": "75.02", "q": "0.5", "m": False,
            }},
        ])
        self.closed = False

    def recv(self):
        return json.dumps(next(self.frames))

    def close(self):
        self.closed = True

    def ping(self):
        return None


def test_public_depth_archive_is_contiguous_hashed_and_calibratable(tmp_path):
    connection = FakeConnection()
    ticks = iter([1_000, 1_000, 1_005, 1_015, 1_025, 1_030])
    output = tmp_path / "SOLUSDT.jsonl"

    metadata = record_public_depth(
        "SOLUSDT",
        output,
        duration_sec=60,
        max_events=3,
        session=FakeSession(),
        connect=lambda *args, **kwargs: connection,
        clock_ms=lambda: next(ticks),
    )

    assert connection.closed is True
    assert metadata["contains_secrets"] is False
    assert metadata["depth_event_count"] == 1
    assert metadata["trade_event_count"] == 1
    assert metadata["archive_sha256"] == archive_sha256(output)
    metadata_path = output.with_suffix(".jsonl.metadata.json")
    assert json.loads(metadata_path.read_text())["archive_sha256"] == metadata[
        "archive_sha256"
    ]
    assert not list(tmp_path.glob(".*.tmp"))
    assert stream_url("SOLUSDT").endswith(
        "solusdt@depth@100ms/solusdt@aggTrade"
    )
    events = load_jsonl_archive(output)
    calibration = calibrate_market_events(
        events,
        source_sha256=archive_sha256(output),
        min_book_events=2,
        min_trades=1,
    )
    assert calibration.eligible is True
    assert calibration.latency_source == "public_event_receive"
    assert calibration.latency_ms_p95 >= 0


def test_public_depth_archive_rejects_sequence_gap(tmp_path):
    connection = FakeConnection()
    connection.frames = iter([
        {"data": {
            "e": "depthUpdate", "E": 1_010, "s": "SOLUSDT",
            "U": 101, "u": 101, "b": [], "a": [],
        }},
        {"data": {
            "e": "depthUpdate", "E": 1_020, "s": "SOLUSDT",
            "U": 103, "u": 103, "b": [], "a": [],
        }},
    ])
    import pytest
    with pytest.raises(ValueError, match="sequence gap"):
        record_public_depth(
            "SOLUSDT",
            tmp_path / "broken.jsonl",
            duration_sec=1,
            max_events=3,
            session=FakeSession(),
            connect=lambda *args, **kwargs: connection,
            clock_ms=lambda: 1_000,
        )
    assert not (tmp_path / "broken.jsonl").exists()


def test_public_depth_archive_flushes_pre_sync_trades(tmp_path):
    connection = FakeConnection()
    connection.frames = iter([
        {"data": {
            "e": "aggTrade", "E": 1_005, "s": "SOLUSDT",
            "a": 1233, "p": "75.01", "q": "0.2", "m": True,
        }},
        {"data": {
            "e": "depthUpdate", "E": 1_010, "s": "SOLUSDT",
            "U": 101, "u": 101, "b": [], "a": [],
        }},
    ])
    output = tmp_path / "buffered.jsonl"
    ticks = iter([1_000, 1_000, 1_005, 1_015, 1_020, 1_025])

    metadata = record_public_depth(
        "SOLUSDT",
        output,
        duration_sec=60,
        max_events=3,
        session=FakeSession(),
        connect=lambda *args, **kwargs: connection,
        clock_ms=lambda: next(ticks),
    )

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row.get("e", "snapshot") for row in rows] == [
        "snapshot", "aggTrade", "depthUpdate",
    ]
    assert metadata["trade_event_count"] == 1
    assert metadata["depth_event_count"] == 1
    assert metadata["event_count"] == 3


def test_public_depth_archive_rejects_pre_sync_buffer_overflow(tmp_path):
    connection = FakeConnection()
    connection.frames = iter([
        {"data": {
            "e": "aggTrade", "E": 1_005, "s": "SOLUSDT",
            "a": 1233, "p": "75.01", "q": "0.2", "m": True,
        }},
        {"data": {
            "e": "aggTrade", "E": 1_006, "s": "SOLUSDT",
            "a": 1234, "p": "75.02", "q": "0.3", "m": False,
        }},
    ])
    output = tmp_path / "overflow.jsonl"
    import pytest

    with pytest.raises(ValueError, match="pre-sync trade buffer"):
        record_public_depth(
            "SOLUSDT",
            output,
            duration_sec=60,
            max_events=3,
            session=FakeSession(),
            connect=lambda *args, **kwargs: connection,
            clock_ms=lambda: 1_000,
        )

    assert connection.closed is True
    assert not output.exists()
    assert not output.with_suffix(".jsonl.metadata.json").exists()
