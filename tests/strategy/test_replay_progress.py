import json

import pytest

from bin import replay_historical_entries as replay
from ladder_dragon.strategy.prediction import replay_progress as progress
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


def binding():
    return {"path": {"start_ms": 1, "entry_end_ms": 2, "end_ms": 3, "cutoff_ms": 3},
            "jobs": [{"policy": {"symbol": "SOLUSDT"}, "context_sha256": "a" * 64}],
            "context_evidence_sha256s": ["b" * 64]}


def report():
    return {"status": "COMPLETE_SELECTION_REPLAY", "mode": "SHADOW", "apply_allowed": False,
            "policy": {"symbol": "SOLUSDT"}, "context_sha256": "a" * 64,
            "start_ts_ms": 1, "entry_end_ts_ms": 2, "end_ts_ms": 3, "cutoff_ts_ms": 3}


def test_checkpoint_roundtrip_and_immutable_write(tmp_path):
    c = progress.PathCheckpoint(tmp_path, binding())
    assert c.read() is None
    c.write([report()])
    assert c.read() == [report()]
    with pytest.raises(FileExistsError):
        c.write([report()])


@pytest.mark.parametrize("change", ["context", "policy", "cutoff", "implementation"])
def test_changed_inputs_never_reuse_checkpoint(tmp_path, monkeypatch, change):
    b = binding()
    progress.PathCheckpoint(tmp_path, b).write([report()])
    if change == "context": b["context_evidence_sha256s"] = ["c" * 64]
    if change == "policy": b["jobs"][0]["policy"]["symbol"] = "ETHUSDT"
    if change == "cutoff": b["path"]["cutoff_ms"] = 4
    if change == "implementation": monkeypatch.setattr(progress, "implementation_identity", lambda: {"code": "different"})
    assert progress.PathCheckpoint(tmp_path, b).read() is None


@pytest.mark.parametrize("key,value", [("status", "INCOMPLETE_HISTORY"), ("apply_allowed", True),
                                      ("cutoff_ts_ms", 4), ("context_sha256", "foreign")])
def test_invalid_reports_never_checkpoint(tmp_path, key, value):
    r = report(); r[key] = value
    with pytest.raises(ValueError): progress.PathCheckpoint(tmp_path, binding()).write([r])


def test_corruption_and_capacity_fail_closed(tmp_path, monkeypatch):
    c = progress.PathCheckpoint(tmp_path, binding()); c.write([report()])
    p = json.loads(c.path.read_text()); p["reports"][0]["apply_allowed"] = True
    c.path.write_text(json.dumps(p))
    with pytest.raises(ValueError): c.read()
    monkeypatch.setattr(progress, "MAX_CHECKPOINT_BYTES", 1)
    with pytest.raises(ValueError): progress.PathCheckpoint(tmp_path, binding())


def test_full_inventory_preserves_pending_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "MAX_CHECKPOINTS", 1)
    c = progress.PathCheckpoint(tmp_path, binding()); c.write([report()])
    assert progress.PathCheckpoint(tmp_path, binding()).read() == [report()]
    b = binding(); b["context_evidence_sha256s"] = ["changed"]
    with pytest.raises(ValueError): progress.PathCheckpoint(tmp_path, b).write([report()])
    assert progress.PathCheckpoint(tmp_path, binding()).read() == [report()]


def test_completed_paths_survive_interruption_and_match_uninterrupted(tmp_path, monkeypatch):
    paths = [{"archives": [{"path": str(i), "sha256": str(i) * 64}],
              "start_ms": i * 10 + 1, "entry_end_ms": i * 10 + 2,
              "end_ms": i * 10 + 3, "cutoff_ms": i * 10 + 3} for i in range(3)]
    request = {"request_schema_version": 2, "cohort_contract": replay.COHORT_CONTRACT,
               "stability_block_index": 0, "policy": {"symbol": "SOLUSDT", "classifier_fingerprint": "x"}, "paths": paths}
    source = tmp_path / "request.json"; source.write_text(json.dumps(request))
    monkeypatch.setattr(replay, "_validated_segments", lambda p, _: [(p, {"archive_sha256": p["archives"][0]["sha256"], "symbol": "SOLUSDT"})])
    monkeypatch.setattr(replay, "export_context", lambda *a, **kw: {"context": [{"observed_at_ms": kw["start_ms"]}]})
    monkeypatch.setattr(replay, "iter_segment_events", lambda *a, **kw: iter(()))
    calls = []; interrupt = [True]
    def run(events, *, jobs, **window):
        calls.append(window["start_ms"])
        if window["start_ms"] == 11 and interrupt[0]: raise KeyboardInterrupt()
        r = report(); r.update({k.replace("_ms", "_ts_ms"): v for k, v in window.items()})
        r.update(policy=jobs[0][0], context_sha256=fingerprint({"rows": jobs[0][1]}))
        return [r]
    monkeypatch.setattr(replay, "historical_entry_replays", run)
    monkeypatch.setattr(replay, "_combined_path_report", lambda request, parts: {"parts": parts})
    resumed = tmp_path / "resumed"; resumed.mkdir()
    with pytest.raises(KeyboardInterrupt): replay.run_replay_request_batch([(source, resumed / "result.json")], context_db=tmp_path / "context")
    assert not (resumed / "result.json").exists()
    assert len(list((resumed / ".path-checkpoints").glob("*.json"))) == 1
    interrupt[0] = False
    result = replay.run_replay_request_batch([(source, resumed / "result.json")], context_db=tmp_path / "context")
    assert calls == [1, 11, 11, 21]
    fresh = tmp_path / "fresh"; fresh.mkdir()
    expected = replay.run_replay_request_batch([(source, fresh / "result.json")], context_db=tmp_path / "context")
    assert result == expected


def test_timeout_status_is_published_after_child_exit(tmp_path, monkeypatch):
    from ladder_dragon.strategy import depth_processing as subject
    events = []
    class Child:
        returncode = None
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def poll(self): return self.returncode
        def kill(self): events.append("kill"); self.returncode = -9
        def wait(self, **kwargs): events.append("wait"); return self.returncode
    class Stop:
        def wait(self, seconds): return False
    monkeypatch.setattr(subject.subprocess, "Popen", lambda *a, **kw: Child())
    times = iter([0, 1801]); monkeypatch.setattr(subject.time, "monotonic", lambda: next(times))
    def publish(directory, status, **kw):
        assert events == ["kill", "wait"]
        assert status == "TIMED_OUT" and kw["timeout_seconds"] == 1800
    monkeypatch.setattr(progress, "progress", publish)
    assert subject._run_offline(["bin.historical_replay_runner", "--output-directory", str(tmp_path)], Stop(), timeout_seconds=1800) == -9
