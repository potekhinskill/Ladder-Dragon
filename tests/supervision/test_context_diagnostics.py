import json
import os
import subprocess
import sys

import pytest

from ladder_dragon.supervision.context_diagnostics import (
    ContextDiagnostics, MAX_BYTES, MAX_EVENTS, RETENTION_MS,
)


def event(at=1_000):
    return {"observed_at_ms": at, "stage": "FILTER_SOURCE", "category": "NETWORK"}


def test_restart_and_success_preserve_failure(tmp_path):
    path = tmp_path / "diagnostics.json"
    expected = ContextDiagnostics(path).update([event()], 1_000)
    assert ContextDiagnostics(path).update([], 2_000) == expected
    assert path.stat().st_mode & 0o777 == 0o600
    assert expected["category_counts"] == {"NETWORK": 1}


def test_capacity_and_retention(tmp_path):
    store = ContextDiagnostics(tmp_path / "diagnostics.json")
    for i in range(MAX_EVENTS + 10):
        result = store.update([event(1_000 + i)], 1_000 + i)
    assert result["retained_failure_count"] == MAX_EVENTS
    assert store.path.stat().st_size < MAX_BYTES
    assert store.update([], RETENTION_MS + 2_000)["last_failure"] is None
    assert json.loads(store.path.read_text())["events"] == []


@pytest.mark.parametrize("contents", [b"broken", b"x" * (MAX_BYTES + 1),
    json.dumps({"schema_version": 1, "events": [dict(event(), extra="private-sentinel")]}).encode(),
    json.dumps({"schema_version": 1, "events": [event(100_000)]}).encode()])
def test_invalid_state_is_not_repaired(tmp_path, contents):
    path = tmp_path / "diagnostics.json"
    path.write_bytes(contents)
    with pytest.raises(ValueError):
        ContextDiagnostics(path).update([event()], 2_000)
    assert path.read_bytes() == contents


def test_atomic_failure_preserves_previous_file(tmp_path, monkeypatch):
    store = ContextDiagnostics(tmp_path / "diagnostics.json")
    store.update([event()], 1_000)
    before = store.path.read_bytes()
    def fail(*args):
        raise OSError("private-sentinel")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.update([event(2_000)], 2_000)
    assert store.path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [store.path]


def test_symlink_is_not_read(tmp_path):
    target = tmp_path / "target"
    target.write_text("private-sentinel")
    path = tmp_path / "diagnostics.json"
    path.symlink_to(target)
    with pytest.raises(OSError):
        ContextDiagnostics(path).update([event()], 1_000)
    assert target.read_text() == "private-sentinel"


@pytest.mark.parametrize("temporary", [False, True])
def test_fifo_is_rejected_without_waiting(tmp_path, temporary):
    path = tmp_path / "diagnostics.json"
    fifo = path.with_name(f".{path.name}.tmp") if temporary else path
    os.mkfifo(fifo)
    code = """
import sys
from pathlib import Path
from ladder_dragon.supervision.context_diagnostics import ContextDiagnostics
try:
    ContextDiagnostics(Path(sys.argv[1])).update([
        {'observed_at_ms': 1000, 'stage': 'FILTER_SOURCE', 'category': 'NETWORK'}], 1000)
except (OSError, ValueError):
    sys.exit(0)
sys.exit(1)
"""
    result = subprocess.run([sys.executable, "-c", code, str(path)],
                            capture_output=True, timeout=5)
    assert result.returncode == 0


def test_temporary_hardlink_does_not_truncate_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("private-sentinel")
    path = tmp_path / "diagnostics.json"
    os.link(target, path.with_name(f".{path.name}.tmp"))
    with pytest.raises(ValueError):
        ContextDiagnostics(path).update([event()], 1_000)
    assert target.read_text() == "private-sentinel"
