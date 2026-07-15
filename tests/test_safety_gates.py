import importlib.util
from pathlib import Path
import subprocess
import sys

import ai_supervisor


def load_worker():
    path = Path("1.8_autosize_universal.py").resolve()
    spec = importlib.util.spec_from_file_location("ladder_worker", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_supervisor_dry_cancel_never_reaches_transport(monkeypatch):
    ai_supervisor.LIVE_MODE = False
    monkeypatch.setattr(
        ai_supervisor,
        "_canonical_signed_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transport called")),
    )
    assert ai_supervisor.cancel_order("SOLUSDT", 123) is False


def test_worker_dry_blocks_every_mutating_signed_request():
    worker = load_worker()
    worker.LIVE_MODE = False
    try:
        worker._signed_request("DELETE", "/api/v3/order", {})
    except RuntimeError as exc:
        assert "DRY mode blocked" in str(exc)
    else:
        raise AssertionError("mutating request was not blocked")


def test_worker_symbol_lock_respects_bot_run_dir(tmp_path, monkeypatch):
    worker = load_worker()
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    lock = worker.SymbolLock("SOLUSDT")

    assert lock.acquire() is True
    assert Path(lock.path).parent == tmp_path
    lock.release()
    assert not Path(lock.path).exists()


def test_supervisor_exponentially_backs_off_crashing_children(monkeypatch):
    monkeypatch.setenv("BOT_CHILD_RESTART_BASE_SEC", "2")
    monkeypatch.setenv("BOT_CHILD_RESTART_MAX_SEC", "10")
    monkeypatch.setenv("BOT_CHILD_STABLE_SEC", "30")
    ai_supervisor._CHILD_FAILURES.clear()
    ai_supervisor._CHILD_RESTART_AFTER.clear()

    assert ai_supervisor._schedule_child_restart("SOLUSDT", 1, 1, now=100) == 2
    assert ai_supervisor._schedule_child_restart("SOLUSDT", 1, 1, now=101) == 4
    assert ai_supervisor._schedule_child_restart("SOLUSDT", 0, 60, now=102) == 0
    assert ai_supervisor._CHILD_FAILURES["SOLUSDT"] == 0


def test_unknown_supervisor_flag_is_fatal():
    result = subprocess.run(
        [sys.executable, "ai_supervisor.py", "--definitely-unknown"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_dry_supervisor_refuses_missing_worker_file():
    result = subprocess.run(
        [
            sys.executable,
            "ai_supervisor.py",
            "--base-script",
            "definitely-missing-worker.py",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--base-script does not exist" in result.stderr


def test_live_requires_explicit_confirmation(monkeypatch):
    env = dict(**__import__("os").environ)
    env.pop("BOT_LIVE_CONFIRMED", None)
    result = subprocess.run(
        [
            sys.executable,
            "ai_supervisor.py",
            "--live",
            "--base-script",
            "1.8_autosize_universal.py",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2
    assert "BOT_LIVE_CONFIRMED=YES" in result.stderr
