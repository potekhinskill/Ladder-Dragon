from pathlib import Path

import pytest

from ladder_dragon.execution.auth_resilience import (
    AuthResilienceState,
    accept_public_ip_fingerprint,
    load_auth_state,
    observe_public_ip_fingerprint,
    public_ip_fingerprint,
    register_auth_failure,
    register_auth_success,
    save_auth_state,
)


def test_auth_backoff_survives_restart_without_secret_or_ip(tmp_path):
    path = tmp_path / "auth.json"
    raw_ip = "203.0.113.71"
    fingerprint = public_ip_fingerprint(raw_ip)
    state = observe_public_ip_fingerprint(
        AuthResilienceState(), fingerprint, now_epoch=100
    )
    state = register_auth_failure(
        state, initial_sec=60, max_sec=900, now_epoch=200
    )
    save_auth_state(path, state)

    restored = load_auth_state(path)

    assert restored.attempt == 1
    assert restored.retry_at_epoch == 260
    assert restored.public_ip_sha256 == fingerprint
    assert raw_ip not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_changed_ip_stays_blocked_until_explicit_acceptance():
    first = public_ip_fingerprint("203.0.113.10")
    second = public_ip_fingerprint("203.0.113.11")
    baseline = observe_public_ip_fingerprint(
        AuthResilienceState(), first, now_epoch=10
    )

    changed = observe_public_ip_fingerprint(
        baseline, second, now_epoch=20
    )

    assert changed.public_ip_changed is True
    assert changed.public_ip_sha256 == first
    accepted = accept_public_ip_fingerprint(
        changed, second, now_epoch=30
    )
    assert accepted.public_ip_changed is False
    assert register_auth_success(accepted, now_epoch=40).attempt == 0


def test_invalid_auth_state_fails_validation(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text('{"schema_version":1,"attempt":-1}')
    with pytest.raises(ValueError, match="bounds"):
        load_auth_state(path)
