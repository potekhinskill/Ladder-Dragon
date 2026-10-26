"""Latency ownership, historical syntax, descriptor lifetime and consumer parity."""

import ast
import json
from pathlib import Path
import shutil
import sys

import pytest

from ladder_dragon.observability import latency_trace as timing
from ladder_dragon.verification.architecture.latency_trace import OWNER, OWNER_PATH, CONSUMERS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest

ROOT = Path(__file__).resolve().parents[2]
# Captured before this move, with the earlier startup-timing move already present.
DIGESTS = {
    OWNER_PATH: "ec5a71ac4de56dc80888af4d41be79bed231edd90e4396d363481169268fc2e8",
    CONSUMERS[0]: "48846fbd0ffb6afad5b270ea059052dc582c5442465b142960c96051cf89a909",
    CONSUMERS[1]: "56c659d15817e3e94470e7293cf6b251ba196f4c8fd64d5a9342c652a9ce1626",
}


@pytest.mark.parametrize("path", DIGESTS)
def test_syntax_matches_before_relocation(path):
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == OWNER:
            node.module = "ladder_dragon.execution.latency_trace"
    assert extraction_digest(tree) == DIGESTS[path]


def test_real_consumers_share_class_and_payload_is_detached(tmp_path):
    from ladder_dragon.supervision import runtime as supervisor
    from ladder_dragon.execution.worker import runtime as worker

    assert supervisor.LatencyTrace is worker.LatencyTrace is timing.LatencyTrace
    trace = worker.LatencyTrace("solusdt", "buy", monotonic_ns=lambda: 5, wall_time_ms=lambda: 7)
    trace.mark("journal_commit")
    payload = trace.payload()
    payload["phases_us"]["journal_commit"] = 123
    target = tmp_path / "nested" / "trace.ndjson"
    first = trace.append(target)
    trace.mark("request_sent")
    second = trace.append(target)
    assert [json.loads(line) for line in target.read_text().splitlines()] == [first, second]
    assert first["phases_us"] == {"journal_commit": 0}
    assert second["phases_us"] == {"journal_commit": 0, "request_sent": 0}
    assert target.stat().st_mode & 0o777 == 0o600


def test_failed_write_closes_descriptor_and_propagates(tmp_path, monkeypatch):
    closed = []
    real_close = timing.os.close
    def close(fd):
        closed.append(fd)
        real_close(fd)
    def fail(fd, data):
        raise OSError("synthetic write failure")
    monkeypatch.setattr(timing.os, "close", close)
    monkeypatch.setattr(timing.os, "write", fail)
    with pytest.raises(OSError, match="synthetic write failure"):
        timing.LatencyTrace("SOLUSDT", "BUY").append(tmp_path / "trace.ndjson")
    assert len(closed) == 1


@pytest.mark.parametrize("profile", ("local", "release"))
@pytest.mark.parametrize("damage", (
    None, "missing", "syntax", "stub", "method_stub", "payload_stub", "reverse", "relative",
    "legacy", "supervisor_import", "worker_import", "shadow",
))
def test_required_ownership_contract(tmp_path, profile, damage):
    for path in (OWNER_PATH, *CONSUMERS):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    owner = tmp_path / OWNER_PATH
    supervisor, worker = (tmp_path / path for path in CONSUMERS)
    if damage == "missing":
        owner.unlink()
    elif damage == "syntax":
        owner.write_text("class")
    elif damage == "stub":
        owner.write_text("from legacy import LatencyTrace\n")
    elif damage in {"method_stub", "payload_stub"}:
        tree = ast.parse(owner.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        name = "append" if damage == "method_stub" else "payload"
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        method.body = ast.parse("return legacy()").body
        owner.write_text(ast.unparse(tree))
    elif damage in {"reverse", "relative"}:
        owner.write_text(owner.read_text() + ("\nimport ladder_dragon.execution.worker.runtime\n"
                         if damage == "reverse" else "\nfrom ..execution import worker\n"))
    elif damage == "legacy":
        target = tmp_path / "ladder_dragon/execution/latency_trace.py"
        target.write_text("from ladder_dragon.observability.latency_trace import LatencyTrace\n")
    elif damage in {"supervisor_import", "worker_import"}:
        target = supervisor if damage == "supervisor_import" else worker
        target.write_text(target.read_text().replace(OWNER, "ladder_dragon.execution.latency_trace"))
    elif damage == "shadow":
        worker.write_text(worker.read_text() + "\nLatencyTrace = lambda *args: None\n")
    context = HarnessContext(root=tmp_path, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=tmp_path / "report.json"))
    spec, = [s for s in checks_for_profile(context) if s.name == "architecture_latency_trace"]
    assert spec.required
    result = HarnessRunner(context)._run_spec(spec)
    expected = (Status.PASS if damage is None else Status.BLOCKED
                if damage in {"missing", "syntax"} else Status.FAILED)
    assert result.status is expected, result.metrics
