"""Focused regressions for persistent public IP alert transitions."""

import inspect

from ladder_dragon.execution.auth_resilience import (
    AuthResilienceState,
    public_ip_fingerprint,
)
from ladder_dragon.supervision import runtime as supervisor


class _Response:
    text = "203.0.113.11"

    @staticmethod
    def raise_for_status():
        return None


def test_same_pending_public_ip_alerts_only_once(tmp_path, monkeypatch):
    baseline = AuthResilienceState(
        public_ip_sha256=public_ip_fingerprint("203.0.113.10")
    )
    notices = []
    monkeypatch.setenv(
        "BINANCE_AUTH_STATE_FILE", str(tmp_path / "auth.json")
    )
    monkeypatch.setenv(
        "BINANCE_PUBLIC_IP_ENDPOINTS",
        "https://one.example.invalid,https://two.example.invalid",
    )
    monkeypatch.setattr(
        supervisor.requests, "get", lambda *_args, **_kwargs: _Response()
    )
    monkeypatch.setattr(
        supervisor,
        "notify_public_ip_change",
        lambda: notices.append("changed") or True,
    )

    changed, first_consensus = supervisor._observe_public_ip(baseline)
    repeated, second_consensus = supervisor._observe_public_ip(changed)

    assert first_consensus == second_consensus
    assert repeated.pending_public_ip_sha256 == first_consensus
    assert notices == ["changed"]


def test_runtime_auth_recovery_accepts_pending_ip_before_notice():
    source = inspect.getsource(supervisor.main)
    start = source.index("if auth_failure_attempts:")
    end = source.index("auth_failure_attempts = 0", start)
    recovery = source[start:end]

    finalize_at = recovery.index("finalize_auth_success(")
    save_at = recovery.index("_save_auth_resilience_state(")
    notify_at = recovery.index("notify_binance_auth_recovered(")

    assert finalize_at < save_at < notify_at
    assert "_publish_ai_runtime_status(ip_guard=" in recovery
