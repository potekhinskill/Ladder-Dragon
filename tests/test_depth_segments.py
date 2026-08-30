import json
from pathlib import Path

import pytest

from ladder_dragon.strategy.depth_capture import (
    PublicStreamReconnect,
    capture_segments,
    public_snapshot,
)
from ladder_dragon.strategy.depth_processing import calibration_inventory, calibrate_segment
from ladder_dragon.strategy.depth_segments import (
    MAX_FRAME_BYTES, atomic_json, bounded_json, iter_segment_events, verified_segments,
)


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.body


class Session:
    def __init__(self):
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        assert kwargs["stream"] is True
        return Response(json.dumps({"lastUpdateId": 100, "bids": [["100", "5"]],
                                    "asks": [["101", "5"]]}).encode())


def depth(index):
    return {"e": "depthUpdate", "s": "SOLUSDT", "E": 1000 + index,
            "U": index, "u": index, "b": [["100", str(index)]], "a": []}


def trade(index):
    return {"e": "aggTrade", "s": "SOLUSDT", "E": 1000 + index,
            "a": index, "p": "100", "q": "1", "m": True}


def record(tmp_path, rows, *, max_events=3):
    class Connection:
        def __init__(self):
            self.rows = list(rows)
            self.closed = False
            self.calls = 0

        def recv(self):
            self.calls += 1
            return json.dumps(self.rows.pop(0))

        def close(self):
            self.closed = True

    connection = Connection()
    http = Session()
    connections = []
    ticks = iter(range(2000, 200000))

    def connect(*args, **kwargs):
        connections.append(args)
        return connection

    metadata = capture_segments("SOLUSDT", tmp_path, duration_sec=1000,
                                max_events=max_events, session=http, connect=connect,
                                stop_requested=lambda: not connection.rows,
                                clock_ms=lambda: next(ticks))
    assert len(connections) == http.calls == 1
    assert connection.closed
    paths = sorted(tmp_path.glob("*.jsonl"))
    return metadata, paths


def test_rotation_carries_book_trade_ids_and_one_connection(tmp_path):
    metadata, paths = record(tmp_path, [depth(101), trade(1), depth(102), trade(2), depth(103), trade(3)])
    assert len(paths) == 3
    events = list(iter_segment_events(verified_segments(paths)))
    assert [event.trades[0][1] for event in events if event.trades] == [1, 1, 1]
    assert len(events) == 6  # one seed, five real events; no rotation duplicates
    assert metadata[1]["previous_archive_sha256"] == metadata[0]["archive_sha256"]
    assert metadata[1]["first_snapshot_update_id"] == metadata[0]["last_update_id"]
    assert metadata[2]["first_trade_id"] == metadata[1]["last_trade_id"]


@pytest.mark.parametrize("field", ["e", "event"])
def test_server_shutdown_commits_the_last_valid_segment(tmp_path, field):
    shutdown = {field: "serverShutdown", "E": 2000}

    with pytest.raises(PublicStreamReconnect, match="server shutdown"):
        record(tmp_path, [depth(101), depth(102), shutdown], max_events=20)

    paths = list(tmp_path.glob("*.jsonl"))
    assert len(paths) == 1
    metadata = bounded_json(paths[0].with_suffix(".jsonl.metadata.json"))
    assert metadata["end_reason"] == "SERVER_SHUTDOWN"
    assert list(iter_segment_events(verified_segments(paths)))
    assert not list(tmp_path.glob(".*.tmp"))


def test_missing_middle_segment_cannot_be_joined(tmp_path):
    _, paths = record(tmp_path, [depth(101), depth(102), depth(103), depth(104), depth(105), depth(106)])
    with pytest.raises(ValueError, match="boundary"):
        verified_segments([paths[0], paths[2]])


@pytest.mark.parametrize("bad", [depth(104), trade(3)])
def test_capture_rejects_depth_or_trade_gaps(tmp_path, bad):
    with pytest.raises(ValueError, match="sequence gap"):
        record(tmp_path, [depth(101), trade(1), depth(102), bad], max_events=20)
    assert not list(tmp_path.glob("*.metadata.json"))
    assert list(tmp_path.glob(".*.tmp"))  # damaged evidence is not published or auto-deleted


def test_hash_tampering_is_rejected_before_replay(tmp_path):
    _, paths = record(tmp_path, [depth(101), depth(102)])
    paths[0].write_bytes(paths[0].read_bytes() + b"{}\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        verified_segments(paths)


def test_metadata_cannot_forge_carried_book(tmp_path):
    _, paths = record(tmp_path, [depth(101), depth(102), depth(103), depth(104)])
    from ladder_dragon.strategy.market_replay import archive_sha256
    lines = paths[1].read_text().splitlines()
    seed = json.loads(lines[0])
    seed["bids"][0][1] = "9999"
    paths[1].write_text(json.dumps(seed) + "\n" + "\n".join(lines[1:]) + "\n")
    sidecar = paths[1].with_suffix(".jsonl.metadata.json")
    meta = bounded_json(sidecar)
    meta["archive_sha256"] = archive_sha256(paths[1])
    sidecar.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="carried book"):
        list(iter_segment_events(verified_segments(paths)))


def test_public_fields_are_whitelisted(tmp_path):
    row = dict(depth(102), apiKey="secret-sentinel", signature="signed-secret")
    _, paths = record(tmp_path, [depth(101), row])
    assert "secret-sentinel" not in paths[0].read_text()
    assert "signature" not in paths[0].read_text()


def test_public_response_is_bounded_before_json():
    class HugeSession:
        def get(self, *args, **kwargs):
            return Response(b"x" * (MAX_FRAME_BYTES + 1))
    with pytest.raises(ValueError, match="byte limit"):
        public_snapshot(HugeSession(), "SOLUSDT")


def test_calibration_backlog_does_not_invent_high(tmp_path):
    _, paths = record(tmp_path, [depth(101), depth(102), trade(1)])
    report, pending = calibration_inventory(tmp_path)
    assert pending == paths
    assert report["high_coverage_conclusion"] == "BACKLOG_NOT_CALIBRATED"
    calibrate_segment(paths[0])
    report, pending = calibration_inventory(tmp_path)
    assert not pending
    assert report["calibration_reports"] == 1
    assert report["high_coverage_conclusion"] == "NOT_OBSERVED"
    assert report["order_validation_proven"] is False
    assert report["status"] == "INCOMPLETE"
    with pytest.raises(FileExistsError):
        calibrate_segment(paths[0])


def test_atomic_immutable_report_never_overwrites(tmp_path):
    path = tmp_path / "report.json"
    atomic_json(path, {"a": 1})
    with pytest.raises(FileExistsError):
        atomic_json(path, {"a": 2})
    assert bounded_json(path) == {"a": 1}


def test_capacity_failure_preserves_old_and_pending_files(tmp_path):
    from ladder_dragon.strategy.depth_capture import remaining_capacity
    old = tmp_path / "old-public.jsonl"
    pending = tmp_path / ".pending.jsonl.tmp"
    old.write_bytes(b"a" * 100)
    pending.write_bytes(b"b" * 100)
    assert remaining_capacity(tmp_path, 150) < 0
    assert old.read_bytes() == b"a" * 100
    assert pending.read_bytes() == b"b" * 100


def test_snapshot_range_cannot_be_widened_by_sparse_diffs():
    from ladder_dragon.strategy.depth_segments import PublicBook
    book = PublicBook()
    book.apply({"lastUpdateId": 1, "_received_at_ms": 1,
                "bids": [["100", "1"], ["90", "1"]],
                "asks": [["101", "1"], ["110", "1"]]})
    book.apply({"e": "depthUpdate", "U": 2, "u": 2, "_received_at_ms": 2,
                "b": [["1", "999"]], "a": [["999", "1"]]})
    assert min(book.bids) == 90
    assert max(book.asks) == 110


def test_regime_boundaries_are_not_relaxed():
    from decimal import Decimal
    from ladder_dragon.strategy.replay_readiness import volatility_regime
    assert volatility_regime(Decimal("1.999999")) == "normal"
    assert volatility_regime(Decimal("2")) == "high"


def test_inventory_rejects_string_eligibility(tmp_path):
    _, paths = record(tmp_path, [depth(101), depth(102)])
    calibrate_segment(paths[0])
    report_path = paths[0].with_suffix(".calibration.json")
    payload = bounded_json(report_path)
    payload["eligible"] = "false"
    report_path.write_text(json.dumps(payload))
    report, _ = calibration_inventory(tmp_path)
    assert report["invalid_artifacts"] == 1
    assert report["eligible_regime_counts"] == {}


def test_service_does_not_wait_for_processing_before_capture(tmp_path, monkeypatch):
    from bin import depth_archive_service as service
    states = []

    class Worker:
        def __init__(self, **kwargs):
            assert kwargs["target"] is service.process_backlog

        def start(self):
            states.append("processing")

        def join(self, timeout):
            states.append("joined")

    def capture(*args, **kwargs):
        assert states == ["processing"]
        states.append("capture")

    monkeypatch.setattr(service.threading, "Thread", Worker)
    monkeypatch.setattr(service, "capture_segments", capture)
    monkeypatch.setattr(service.signal, "signal", lambda *args: None)
    monkeypatch.setattr("sys.argv", ["capture", "--directory", str(tmp_path)])
    assert service.main() == 0
    assert states == ["processing", "capture", "joined"]
