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


def test_unknown_supervisor_flag_is_fatal():
    result = subprocess.run(
        [sys.executable, "ai_supervisor.py", "--definitely-unknown"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


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
