"""Preserve observer CLI ownership, signal lifetimes, and failure behavior."""

import ast
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import OBSERVER_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "record_depth_archive": "c9f73dcf5d2efd806e85e89c32d0c1f6c811e0354f0c3c32711fb8ee32169653",
    "depth_archive_service": "b82ba23b86bfeed5701de73a4f9712cac547912768f187d2e7eced20149edbf5",
    "user_stream_shadow": "d24a075c3a515de09109820e95bf2b3955d6dc509d0f54f37ce5157b5a51b2a5",
    "market_scenario_shadow": "3917265ff578d201282450e123b0df5f0cc09e7c6b558e31c9f0bbfcf933a07c",
    "historical_replay_planner": "3cb79783342a3741c0c2d2d50d35adbb8a3f0977ccd0319562a04355d6300b57",
}


def test_build_configuration_includes_runtime_version_module():
    from setuptools.config.pyprojecttoml import read_configuration
    config = read_configuration(ROOT / "pyproject.toml")
    assert "product_version" in config["tool"]["setuptools"]["py-modules"]


@pytest.mark.parametrize("name", OBSERVER_COMMANDS)
def test_syntax_and_safe_executable_path(name, tmp_path):
    source = ROOT / (OBSERVER_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    env = {"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"}
    # This command has no parser: force early rejection before service construction.
    env["BOT_MARKET_ANALYSIS_ROUND_TRIP_COST_PCT"] = "invalid-synthetic-value"
    args = [] if name == "market_scenario_shadow" else ["--help"]
    result = subprocess.run([sys.executable, "-m", f"bin.{name}", *args],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == (2 if name == "market_scenario_shadow" else 0)
    if name == "market_scenario_shadow":
        assert json.loads(result.stdout)["status"] == "BLOCKED"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", OBSERVER_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_harness_rejects_observer_ownership_damage(name, profile, damage, checkout):
    tmp_path = checkout
    source = tmp_path / (OBSERVER_COMMANDS[name].replace(".", "/") + ".py")
    if damage == "launcher":
        path = tmp_path / f"bin/{name}.py"
        path.write_text(path.read_text() + "\ndef misplaced(): return 1\n")
    elif damage == "forwarder":
        source.write_text("def main():\n    return old_runtime()\n")
    elif damage == "reverse":
        source.write_text(source.read_text() + f"\nfrom bin.{name} import main as legacy\n")
    else:
        source.unlink()
    context = HarnessContext(root=tmp_path, python=sys.executable, options=HarnessOptions(
        profile=profile, output=tmp_path / "report.json"))
    check, = [c for c in checks_for_profile(context) if c.name == "architecture_command_ownership"]
    assert check.required
    assert HarnessRunner(context)._run_spec(check).status is (
        Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("fails", [False, True])
def test_depth_service_signals_and_worker_cleanup(fails, tmp_path, monkeypatch):
    from ladder_dragon.strategy import depth_service_command as module
    handlers, events, states = {}, [], []
    monkeypatch.setattr(module.signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
    class Worker:
        def __init__(self, *, target, args, daemon):
            assert target is module.process_backlog and daemon
            events.append(args[1])
        def start(self):
            states.append("start")
        def join(self, timeout):
            assert timeout == 7 and events[0].is_set()
            states.append("join")
    def capture(*args, **kwargs):
        assert states == ["start"] and kwargs["max_segments"] == 1
        assert not kwargs["stop_requested"]()
        handlers[signal.SIGTERM](None, None)
        assert kwargs["stop_requested"]()
        states.append("capture")
        if fails:
            raise ValueError("synthetic")
    monkeypatch.setattr(module.threading, "Thread", Worker)
    monkeypatch.setattr(module, "capture_segments", capture)
    monkeypatch.setattr(sys, "argv", ["service", "--directory", str(tmp_path), "--once"])
    assert module.main() == (2 if fails else 0)
    assert states == ["start", "capture", "join"]


def test_user_stream_signal_events_remain_live(monkeypatch, tmp_path):
    from ladder_dragon.execution import user_stream_command as module
    handlers = {}
    monkeypatch.setattr(module.signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
    def run(config, *, stop_event, reconnect_event, logger):
        assert config.symbol == "SOLUSDT" and config.state_path == tmp_path / "synthetic.json"
        assert not stop_event.is_set() and not reconnect_event.is_set()
        handlers[signal.SIGUSR1](None, None)
        assert reconnect_event.is_set() and not stop_event.is_set()
        handlers[signal.SIGINT](None, None)
        assert stop_event.is_set()
        return 2
    monkeypatch.setattr(module, "run_user_stream_shadow", run)
    monkeypatch.setattr(sys, "argv", ["stream", "--symbol", "solusdt", "--state-path", str(tmp_path / "synthetic.json")])
    assert module.main() == 2 and not list(tmp_path.iterdir())


@pytest.mark.parametrize("status", ["PASS", "BLOCKED"])
def test_scenario_keeps_shadow_output(status, monkeypatch, capsys):
    from ladder_dragon.market_analysis import scenario_command as module
    from decimal import Decimal
    for name in list(os.environ):
        if name.startswith("BOT_MARKET_ANALYSIS_") or name == "BOT_SERVICE_SYMBOLS":
            monkeypatch.delenv(name)
    class Service:
        def __init__(self, **kwargs):
            assert kwargs["round_trip_cost_pct"] == Decimal("0.0025")
            assert kwargs["execution_symbols"] == ("SOLUSDT",)
        def run_once(self):
            return {"status": status}
    monkeypatch.setattr(module, "MarketScenarioService", Service)
    assert module.main() == (0 if status == "PASS" else 2)
    assert json.loads(capsys.readouterr().out)["apply_allowed"] is False


@pytest.mark.parametrize("fails", [False, True])
def test_planner_writes_only_synthetic_status(fails, tmp_path, monkeypatch):
    from ladder_dragon.strategy.prediction import replay_planner_command as module
    (tmp_path / "drafts").mkdir()
    def plan(*args):
        if fails:
            raise ValueError("synthetic")
        return {"status": "PASS", "draft_count": 0, "apply_allowed": False}
    monkeypatch.setattr(module, "plan_replay_drafts", plan)
    monkeypatch.setattr(sys, "argv", ["planner", "--archive-directory", str(tmp_path),
        "--draft-directory", str(tmp_path / "drafts"), "--context-db", str(tmp_path / "synthetic.sqlite")])
    assert module.main() == (2 if fails else 0)
    result = json.loads((tmp_path / "drafts/status.json").read_text())
    assert result["apply_allowed"] is False
    assert result["status"] == ("BLOCKED" if fails else "PASS")
    assert not (tmp_path / "synthetic.sqlite").exists()


@pytest.mark.parametrize("fails", [False, True])
def test_record_command_preserves_arguments_and_failure(fails, monkeypatch, capsys):
    from ladder_dragon.strategy import depth_record_command as module
    def record(symbol, output, **kwargs):
        assert symbol == "SOLUSDT" and output == "synthetic.jsonl"
        assert kwargs == {"duration_sec": 300, "max_events": 100000, "depth_limit": 1000}
        if fails:
            raise ValueError("synthetic")
        return {"synthetic": True}
    monkeypatch.setattr(module, "record_public_depth", record)
    monkeypatch.setattr(sys, "argv", ["record", "--symbol", "SOLUSDT", "--output", "synthetic.jsonl"])
    if fails:
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == 2
    else:
        assert module.main() == 0
        assert json.loads(capsys.readouterr().out) == {"synthetic": True}
