"""Component tests for bounded supervisor child lifecycle policy."""

import signal

import pytest

from ladder_dragon.supervision.process_manager import (
    ChildProcessRegistry,
    SupervisorShutdownSignal,
)


def _registry() -> ChildProcessRegistry:
    return ChildProcessRegistry({}, {}, {}, {}, {})


def test_exponential_backoff_handles_fast_child_failures(monkeypatch):
    monkeypatch.setenv("BOT_CHILD_RESTART_BASE_SEC", "2")
    monkeypatch.setenv("BOT_CHILD_RESTART_MAX_SEC", "10")
    monkeypatch.setenv("BOT_CHILD_STABLE_SEC", "30")
    registry = _registry()

    assert registry.schedule(
        "SOLUSDT", 1, 1, logger=lambda _message: None,
        notifier=lambda *_args: None, now=100,
    ) == 2
    assert registry.schedule(
        "SOLUSDT", 1, 1, logger=lambda _message: None,
        notifier=lambda *_args: None, now=101,
    ) == 4
    assert registry.schedule(
        "SOLUSDT", 0, 60, logger=lambda _message: None,
        notifier=lambda *_args: None, now=102,
    ) == 0
    assert registry.failures["SOLUSDT"] == 0


def test_slow_repeated_failures_back_off_alert_and_expire(monkeypatch):
    alerts = []
    monkeypatch.setenv("BOT_CHILD_RESTART_BASE_SEC", "2")
    monkeypatch.setenv("BOT_CHILD_RESTART_MAX_SEC", "10")
    monkeypatch.setenv("BOT_CHILD_STABLE_SEC", "30")
    monkeypatch.setenv("BOT_CHILD_RESTART_WINDOW_SEC", "3600")
    monkeypatch.setenv("BOT_CHILD_RESTART_WINDOW_LIMIT", "3")
    monkeypatch.setenv("BOT_CHILD_RESTART_ALERT_COUNT", "3")
    registry = _registry()
    notify = lambda *args: alerts.append(args)

    assert registry.schedule(
        "SOLUSDT", 1, 35, logger=lambda _message: None,
        notifier=notify, now=100,
    ) == 0
    assert registry.schedule(
        "SOLUSDT", 1, 35, logger=lambda _message: None,
        notifier=notify, now=200,
    ) == 0
    assert registry.schedule(
        "SOLUSDT", 1, 35, logger=lambda _message: None,
        notifier=notify, now=300,
    ) == 2
    assert len(alerts) == 1
    assert alerts[0][0] == "worker restart storm"
    assert alerts[0][2]["restarts"] == 3
    assert registry.schedule(
        "SOLUSDT", 1, 35, logger=lambda _message: None,
        notifier=notify, now=4001,
    ) == 0
    assert len(alerts) == 1


def test_sigterm_enters_graceful_shutdown_once(monkeypatch):
    installed = {}
    monkeypatch.setattr(
        signal,
        "signal",
        lambda kind, handler: installed.update(
            {"kind": kind, "handler": handler}
        ),
    )
    shutdown = SupervisorShutdownSignal()
    shutdown.install()

    assert installed["kind"] == signal.SIGTERM
    with pytest.raises(KeyboardInterrupt):
        installed["handler"](signal.SIGTERM, None)
    assert shutdown.requested is True
    assert installed["handler"](signal.SIGTERM, None) is None
