"""Focused regressions for persistent public IP alert transitions."""

import inspect
import threading

import requests

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


def test_public_ip_sources_overlap_and_join_before_consensus(monkeypatch):
    barrier = threading.Barrier(2)
    completed = []
    monkeypatch.setenv(
        "BINANCE_PUBLIC_IP_ENDPOINTS",
        "https://one.example.invalid,https://two.example.invalid",
    )

    def get(endpoint, *, timeout):
        assert timeout == 5
        barrier.wait(timeout=2)
        completed.append(endpoint)
        return _Response()

    monkeypatch.setattr(supervisor.requests, "get", get)
    observed, consensus = supervisor._observe_public_ip(AuthResilienceState())

    assert len(completed) == 2
    assert consensus == public_ip_fingerprint(_Response.text)
    assert observed.public_ip_sha256 == consensus


def test_one_public_ip_failure_cannot_create_consensus(monkeypatch, capsys):
    monkeypatch.setenv(
        "BINANCE_PUBLIC_IP_ENDPOINTS",
        "https://one.example.invalid,https://two.example.invalid",
    )

    def get(endpoint, *, timeout):
        if "one." in endpoint:
            raise requests.ConnectionError("synthetic-private-marker")
        return _Response()

    monkeypatch.setattr(supervisor.requests, "get", get)
    observed, consensus = supervisor._observe_public_ip(AuthResilienceState())

    assert observed == AuthResilienceState()
    assert consensus is None
    assert "synthetic-private-marker" not in capsys.readouterr().out


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
