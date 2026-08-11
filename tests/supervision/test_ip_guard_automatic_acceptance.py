"""Automatic public IP acceptance after authoritative read-only authentication."""

import inspect
from types import SimpleNamespace

from ladder_dragon.execution.auth_resilience import (
    AuthResilienceState,
    public_ip_fingerprint,
)
from ladder_dragon.supervision import runtime as supervisor


def _changed_state() -> AuthResilienceState:
    return AuthResilienceState(
        public_ip_sha256=public_ip_fingerprint("203.0.113.10"),
        pending_public_ip_sha256=public_ip_fingerprint("203.0.113.11"),
        public_ip_changed=True,
    )


def test_successful_read_only_preflight_accepts_pending_ip(tmp_path, monkeypatch):
    saved = []
    notices = []
    published = []
    state = _changed_state()
    monkeypatch.setattr(supervisor, "_read_auth_resilience_state", lambda: state)
    monkeypatch.setattr(
        supervisor,
        "_observe_public_ip",
        lambda current: (current, current.pending_public_ip_sha256),
    )
    monkeypatch.setattr(supervisor, "_preflight_live", lambda *_args: None)
    monkeypatch.setattr(
        supervisor,
        "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setattr(
        supervisor, "_save_auth_resilience_state", saved.append
    )
    monkeypatch.setattr(
        supervisor,
        "notify_binance_auth_recovered",
        lambda *, public_ip_accepted: notices.append(public_ip_accepted),
    )
    monkeypatch.setattr(
        supervisor,
        "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )

    supervisor._preflight_with_auth_backoff(
        SimpleNamespace(
            live=True,
            binance_auth_backoff_initial_sec=60,
            binance_auth_backoff_max_sec=120,
        ),
        ["SOLUSDT"],
        SimpleNamespace(halt_file=tmp_path / "halt.json"),
    )

    assert saved[-1].public_ip_sha256 == state.pending_public_ip_sha256
    assert saved[-1].pending_public_ip_sha256 == ""
    assert saved[-1].public_ip_changed is False
    assert {"ip_guard": {"changed": False, "consensus": True}} in published
    assert notices == [True]


def test_auth_retry_preserves_pending_ip_until_success(tmp_path, monkeypatch):
    saved = []
    attempts = []
    state = _changed_state()

    def preflight(*_args):
        attempts.append(True)
        if len(attempts) == 1:
            raise supervisor.TM.BinanceHttpError(
                "HTTP 401: {'code': -2015, 'msg': 'rejected'}"
            )

    monkeypatch.setattr(supervisor, "_read_auth_resilience_state", lambda: state)
    monkeypatch.setattr(
        supervisor,
        "_observe_public_ip",
        lambda current: (current, current.pending_public_ip_sha256),
    )
    monkeypatch.setattr(supervisor, "_preflight_live", preflight)
    monkeypatch.setattr(
        supervisor,
        "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setattr(
        supervisor, "_save_auth_resilience_state", saved.append
    )
    monkeypatch.setattr(
        supervisor, "_wait_for_resilience_retry", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(supervisor, "notify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        supervisor, "_publish_ai_runtime_status", lambda **_updates: None
    )

    supervisor._preflight_with_auth_backoff(
        SimpleNamespace(
            live=True,
            binance_auth_backoff_initial_sec=60,
            binance_auth_backoff_max_sec=120,
        ),
        ["SOLUSDT"],
        SimpleNamespace(halt_file=tmp_path / "halt.json"),
    )

    failed = next(item for item in saved if item.attempt == 1)
    assert failed.public_ip_changed is True
    assert failed.pending_public_ip_sha256 == state.pending_public_ip_sha256
    assert saved[-1].public_ip_changed is False


def test_changed_ip_retries_signed_preflight_each_minute(tmp_path, monkeypatch):
    saved = []
    waits = []
    attempts = []
    state = _changed_state()

    def preflight(*_args):
        attempts.append(True)
        if len(attempts) == 1:
            raise supervisor.TM.BinanceHttpError(
                "HTTP 401: {'code': -2015, 'msg': 'rejected'}"
            )

    monkeypatch.setattr(supervisor, "_read_auth_resilience_state", lambda: state)
    monkeypatch.setattr(
        supervisor,
        "_observe_public_ip",
        lambda current: (current, current.pending_public_ip_sha256),
    )
    monkeypatch.setattr(supervisor, "_preflight_live", preflight)
    monkeypatch.setattr(
        supervisor,
        "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setattr(supervisor, "_save_auth_resilience_state", saved.append)
    monkeypatch.setattr(
        supervisor,
        "_wait_for_resilience_retry",
        lambda _kind, delay, **_kwargs: waits.append(delay),
    )
    monkeypatch.setattr(supervisor, "notify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        supervisor, "_publish_ai_runtime_status", lambda **_updates: None
    )

    supervisor._preflight_with_auth_backoff(
        SimpleNamespace(
            live=True,
            binance_auth_backoff_initial_sec=60,
            binance_auth_backoff_max_sec=900,
        ),
        ["SOLUSDT"],
        SimpleNamespace(halt_file=tmp_path / "halt.json"),
    )

    assert attempts == [True, True]
    assert waits == [60]
    assert saved[-1].public_ip_changed is False


def test_stale_pending_ip_cannot_pass_without_fresh_consensus(tmp_path, monkeypatch):
    state = _changed_state()
    saved = []
    published = []
    monkeypatch.setattr(supervisor, "_read_auth_resilience_state", lambda: state)
    monkeypatch.setattr(
        supervisor, "_observe_public_ip", lambda current: (current, None)
    )
    monkeypatch.setattr(supervisor, "_preflight_live", lambda *_args: None)
    monkeypatch.setattr(
        supervisor, "_save_auth_resilience_state", saved.append
    )
    monkeypatch.setattr(
        supervisor,
        "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )
    monkeypatch.setattr(
        supervisor.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(InterruptedError()),
    )

    try:
        supervisor._preflight_with_auth_backoff(
            SimpleNamespace(
                live=True,
                binance_auth_backoff_initial_sec=60,
                binance_auth_backoff_max_sec=120,
            ),
            ["SOLUSDT"],
            SimpleNamespace(halt_file=tmp_path / "halt.json"),
        )
    except InterruptedError:
        pass
    else:
        raise AssertionError("missing consensus did not keep IP Guard blocked")

    assert not saved
    assert published[-1]["state"] == "IP_BLOCKED"
    assert published[-1]["risk"]["buy_blocked"] is True


def test_non_live_preflight_ignores_persisted_live_ip_change(
    tmp_path,
    monkeypatch,
):
    state = _changed_state()
    saved = []
    monkeypatch.setattr(supervisor, "_read_auth_resilience_state", lambda: state)
    monkeypatch.setattr(
        supervisor,
        "_observe_public_ip",
        lambda _state: (_ for _ in ()).throw(
            AssertionError("non-LIVE mode contacted public IP sources")
        ),
    )
    monkeypatch.setattr(supervisor, "_preflight_live", lambda *_args: None)
    monkeypatch.setattr(
        supervisor,
        "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setattr(supervisor, "_save_auth_resilience_state", saved.append)
    monkeypatch.setattr(
        supervisor, "_publish_ai_runtime_status", lambda **_updates: None
    )

    supervisor._preflight_with_auth_backoff(
        SimpleNamespace(
            live=False,
            binance_auth_backoff_initial_sec=60,
            binance_auth_backoff_max_sec=120,
        ),
        ["SOLUSDT"],
        SimpleNamespace(halt_file=tmp_path / "halt.json"),
    )

    assert saved[-1].public_ip_changed is True
    assert saved[-1].pending_public_ip_sha256 == state.pending_public_ip_sha256


def test_runtime_auth_rejection_observes_ip_before_persisted_backoff():
    source = inspect.getsource(supervisor.main)
    block_start = source.index("if auth_rejected:")
    block_end = source.index("else:", block_start)
    block = source[block_start:block_end]

    observe_at = block.index("_observe_public_ip(runtime_auth_state)")
    retry_cap_at = block.index("auth_failure_retry_max_sec(")
    register_at = block.index("register_auth_failure(")
    save_at = block.index("_save_auth_resilience_state(runtime_auth_state)")

    assert observe_at < register_at < retry_cap_at < save_at
