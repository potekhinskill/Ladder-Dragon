"""Fail-closed supervisor preflight and recovery retry regressions."""

from types import SimpleNamespace

from ladder_dragon.supervision import preflight_resilience
from ladder_dragon.supervision import runtime as ai_supervisor


def test_transient_retry_bounds_are_bounded_and_fail_safe():
    configured = {
        "BINANCE_PREFLIGHT_BACKOFF_INITIAL_SEC": "2",
        "BINANCE_PREFLIGHT_BACKOFF_MAX_SEC": "99999",
    }
    assert preflight_resilience.retry_bounds(
        lambda key, default: configured.get(key, default)
    ) == (5, 3600)
    assert preflight_resilience.retry_bounds(
        lambda _key, _default: "invalid"
    ) == (30, 300)


def test_supervisor_transient_preflight_failure_stays_in_process(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.auth_resilience import AuthResilienceState

    attempts = []
    waits = []
    published = []
    messages = []
    state = AuthResilienceState()

    def preflight(*_args):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("Binance time RTT 5660 ms exceeds 5000 ms")

    monkeypatch.setattr(
        ai_supervisor, "_read_auth_resilience_state", lambda: state
    )
    monkeypatch.setattr(
        ai_supervisor, "_save_auth_resilience_state", lambda _state: None
    )
    monkeypatch.setattr(
        ai_supervisor, "_observe_public_ip", lambda current: current
    )
    monkeypatch.setattr(ai_supervisor, "_preflight_live", preflight)
    monkeypatch.setattr(
        ai_supervisor,
        "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_wait_for_resilience_retry",
        lambda kind, delay, **kwargs: waits.append((kind, delay, kwargs)),
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(ai_supervisor, "_INFO_LOG_LAST_EMITTED", {})
    args = SimpleNamespace(
        live=True,
        binance_auth_backoff_initial_sec=60,
        binance_auth_backoff_max_sec=120,
    )
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json")

    ai_supervisor._preflight_with_auth_backoff(
        args, ["SOLUSDT"], limits
    )

    assert len(attempts) == 2
    assert waits == [
        ("PREFLIGHT", 30, {"attempt": 1, "persistent_halt": False})
    ]
    assert any("PREFLIGHT-BACKOFF" in message for message in messages)
    recovered = [
        row for row in published
        if row.get("preflight_backoff", {}).get("active") is False
    ][-1]
    assert recovered["preflight_backoff"]["attempt"] == 1
    assert published[-1]["recovery"]["blocked"] is False


def test_recovery_blocked_message_is_rate_limited(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.auth_resilience import AuthResilienceState

    recovery_attempts = []
    messages = []

    def recovery(*_args):
        recovery_attempts.append(True)
        if len(recovery_attempts) <= 2:
            raise RuntimeError(
                "reconciled BUY has execution without verified protection"
            )
        return {"checked": 1, "blocked": False}

    monkeypatch.setattr(
        ai_supervisor,
        "_read_auth_resilience_state",
        lambda: AuthResilienceState(),
    )
    monkeypatch.setattr(
        ai_supervisor, "_save_auth_resilience_state", lambda _state: None
    )
    monkeypatch.setattr(
        ai_supervisor, "_observe_public_ip", lambda current: current
    )
    monkeypatch.setattr(ai_supervisor, "_preflight_live", lambda *_args: None)
    monkeypatch.setattr(
        ai_supervisor, "_pre_running_recovery_gate", recovery
    )
    monkeypatch.setattr(ai_supervisor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ai_supervisor.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        ai_supervisor, "_publish_ai_runtime_status", lambda **_updates: None
    )
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(ai_supervisor, "_INFO_LOG_LAST_EMITTED", {})
    args = SimpleNamespace(
        live=True,
        binance_auth_backoff_initial_sec=60,
        binance_auth_backoff_max_sec=120,
    )
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json")

    ai_supervisor._preflight_with_auth_backoff(
        args, ["SOLUSDT"], limits
    )

    recovery_messages = [
        message for message in messages
        if "[RECOVERY] pre-RUNNING gate blocked" in message
    ]
    assert recovery_messages == [
        "[RECOVERY] pre-RUNNING gate blocked; reason="
        "reconciled BUY has execution without verified protection"
    ]


def test_supervisor_auth_backoff_does_not_hide_other_preflight_errors():
    assert preflight_resilience.is_auth_rejection(
        RuntimeError("HTTP 401: {'code': -2015}")
    )
    assert not preflight_resilience.is_auth_rejection(
        RuntimeError("position reconciliation failed")
    )
    assert [
        preflight_resilience.retry_delay(
            attempt, initial_sec=60, max_sec=900
        )
        for attempt in range(1, 7)
    ] == [60, 120, 240, 480, 900, 900]
    delay, retry_at = preflight_resilience.retry_schedule(
        3,
        initial_sec=60,
        max_sec=900,
        now=1_000.0,
    )
    assert (delay, retry_at) == (240, 1_240.0)
    assert preflight_resilience.backoff_active(
        retry_at, now=1_239.0
    )
    assert not preflight_resilience.backoff_active(
        retry_at, now=1_240.0
    )
