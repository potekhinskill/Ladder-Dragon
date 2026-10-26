"""Read telemetry relocation, real consumers, and context restoration."""

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import sys
import threading

import pytest

from ladder_dragon.observability import read_timing as timing
from ladder_dragon.verification.architecture.read_timing import OWNER, OWNER_PATH, CONSUMERS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest, restore_transport_diagnostic_import

ROOT = Path(__file__).resolve().parents[2]
# Captured before relocation from 446b93673e6f1f39353c0ca4dc67da930e3b7a5b.
DIGESTS = {
    OWNER_PATH: "09c736903162fa2f15d403838675ee0530cadb0f3fda7c0f03a0524ab763bc92",
    "ladder_dragon/execution/tools_market.py": "eae2db27feef30ba25bcdfd4ea9e9e5e5500d2cd009e27943a5b5f8144b36f5e",
    "ladder_dragon/supervision/valuation_metrics.py": "01226fe4ea6f243700ed85c29f611cf5d0d7c445c8c1d7d1686cb3b4878daaf1",
    "ladder_dragon/supervision/valuation_reads.py": "81126459f66be5a862b3dca7f9b63485e5cb0dbdfd429dcaa88d2a73de288c73",
}


@pytest.mark.parametrize("path", DIGESTS)
def test_original_syntax_except_reviewed_import(path):
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == OWNER:
            node.module = "ladder_dragon.execution.read_timing"
        if isinstance(node, ast.ImportFrom) and node.module == "ladder_dragon.market_data.tickers":
            node.module = "ladder_dragon.execution.market_tickers"
    assert extraction_digest(restore_transport_diagnostic_import(tree)) == DIGESTS[path]


def test_nested_observers_restore_after_failure_and_reject_private_values():
    outer, inner = [], []
    with timing.observe_reads(lambda *args: outer.append(args)):
        timing.record_read("http_attempts", 1)
        with pytest.raises(ValueError, match="synthetic"):
            with timing.observe_reads(lambda *args: inner.append(args)):
                timing.record_read("http_attempts", 2)
                for key, value in [("private-url", 1), ("http_attempts", True),
                                   ("http_attempts", -1), ("http_attempts", 1.5),
                                   ("http_attempts", "private-payload")]:
                    timing.record_read(key, value)
                raise ValueError("synthetic")
        timing.record_read("http_attempts", 3)
    timing.record_read("http_attempts", 99)
    assert outer == [("http_attempts", 1), ("http_attempts", 3)]
    assert inner == [("http_attempts", 2)]


def test_real_producers_share_one_context_and_isolate_parallel_reads():
    from ladder_dragon.execution import tools_market as market
    from ladder_dragon.supervision import valuation_metrics as metrics
    from ladder_dragon.supervision import valuation_reads as reads

    assert market.record_read is reads.record_read is timing.record_read
    assert market.measured_read is timing.measured_read
    assert metrics.observe_reads is timing.observe_reads
    assert metrics.READ_COUNTERS is timing.COUNTERS
    barrier = threading.Barrier(2)
    capacity = reads.ValuationReads(2)
    outside = []
    def run(count):
        values = metrics.ValuationMetrics()
        def reader():
            barrier.wait(timeout=5)
            market.record_read("http_attempts", count)
            return "private-payload"
        assert values.read("batch", capacity.read, reader) == "private-payload"
        snapshot = values.snapshot(failed=False)
        market.record_read("http_attempts", 99)
        assert values.snapshot(failed=False) == snapshot
        assert snapshot["batch_pool_wait_ms"] >= 0
        assert "private-payload" not in repr(snapshot)
        return snapshot["batch_http_attempts"]
    try:
        with timing.observe_reads(lambda *args: outside.append(args)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run, n) for n in (2, 7)]
                assert [f.result(timeout=10) for f in futures] == [2, 7]
            timing.record_read("http_attempts", 11)
    finally:
        capacity.close()
    assert outside == [("http_attempts", 11)]


@pytest.mark.parametrize("profile", ("local", "release"))
@pytest.mark.parametrize("damage", (
    None, "missing", "syntax", "stub", "reverse", "relative", "context",
    "duplicate_context", "legacy", "market_import", "metrics_import", "pool_import", "shadow",
))
def test_required_read_timing_contract(tmp_path, profile, damage):
    for path in (OWNER_PATH, *CONSUMERS):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    owner = tmp_path / OWNER_PATH
    market, metrics, pool = (tmp_path / path for path in CONSUMERS)
    if damage == "missing":
        owner.unlink()
    elif damage == "syntax":
        owner.write_text("def")
    elif damage == "stub":
        owner.write_text("from legacy import *\n")
    elif damage in {"reverse", "relative"}:
        owner.write_text(owner.read_text() + (
            "\nimport ladder_dragon.execution.tools_market\n" if damage == "reverse"
            else "\nfrom ..execution import tools_market\n"))
    elif damage == "context":
        owner.write_text(owner.read_text().replace('ContextVar("public_read_timing", default=None)', "None"))
    elif damage == "duplicate_context":
        owner.write_text(owner.read_text() + "\n_sink = None\n")
    elif damage == "legacy":
        (market.parent / "read_timing.py").write_text("from ladder_dragon.observability.read_timing import *\n")
    elif damage in {"market_import", "metrics_import", "pool_import"}:
        target = {"market_import": market, "metrics_import": metrics, "pool_import": pool}[damage]
        target.write_text(target.read_text().replace(OWNER, "ladder_dragon.execution.read_timing"))
    elif damage == "shadow":
        market.write_text(market.read_text() + "\nrecord_read = lambda *args: None\n")
    context = HarnessContext(root=tmp_path, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=tmp_path / "report.json"))
    spec, = [s for s in checks_for_profile(context) if s.name == "architecture_read_timing"]
    assert spec.required
    result = HarnessRunner(context)._run_spec(spec)
    expected = (Status.PASS if damage is None else Status.BLOCKED
                if damage in {"missing", "syntax"} else Status.FAILED)
    assert result.status is expected, result.metrics
