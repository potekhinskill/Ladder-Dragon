# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: persist sanitized Binance authentication and public-IP guard state.
"""Fail-closed authentication resilience without persisting secrets or IPs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AuthResilienceState:
    """Sanitized state that survives supervisor and host restarts."""

    attempt: int = 0
    retry_at_epoch: int = 0
    public_ip_sha256: str = ""
    public_ip_changed: bool = False
    updated_at_epoch: int = 0


def public_ip_fingerprint(value: str) -> str:
    """Return a non-reversible identifier and reject malformed responses."""
    candidate = value.strip()
    if not candidate or len(candidate) > 64:
        raise ValueError("public IP response is invalid")
    try:
        normalized = str(ipaddress.ip_address(candidate))
    except ValueError as exc:
        raise ValueError("public IP response is invalid")
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def load_auth_state(path: str | Path) -> AuthResilienceState:
    """Load strictly validated state; corruption blocks optimistic recovery."""
    target = Path(path)
    if not target.exists():
        return AuthResilienceState()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("authentication state schema is invalid")
    attempt = int(payload.get("attempt", 0))
    retry_at = int(payload.get("retry_at_epoch", 0))
    fingerprint = str(payload.get("public_ip_sha256", ""))
    if attempt < 0 or attempt > 1000 or retry_at < 0:
        raise ValueError("authentication state bounds are invalid")
    if fingerprint and (
        len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("public IP fingerprint is invalid")
    return AuthResilienceState(
        attempt=attempt,
        retry_at_epoch=retry_at,
        public_ip_sha256=fingerprint,
        public_ip_changed=bool(payload.get("public_ip_changed", False)),
        updated_at_epoch=int(payload.get("updated_at_epoch", 0)),
    )


def save_auth_state(
    path: str | Path,
    state: AuthResilienceState,
) -> None:
    """Atomically persist allowlisted fields with owner-only permissions."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        **asdict(state),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=str(target.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def register_auth_failure(
    state: AuthResilienceState,
    *,
    initial_sec: int,
    max_sec: int,
    now_epoch: int | None = None,
) -> AuthResilienceState:
    """Advance the persistent bounded exponential retry schedule."""
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    attempt = min(1000, state.attempt + 1)
    exponent = min(max(0, attempt - 1), 16)
    delay = min(int(max_sec), int(initial_sec) * (2 ** exponent))
    return AuthResilienceState(
        attempt=attempt,
        retry_at_epoch=now + delay,
        public_ip_sha256=state.public_ip_sha256,
        public_ip_changed=state.public_ip_changed,
        updated_at_epoch=now,
    )


def register_auth_success(
    state: AuthResilienceState,
    *,
    now_epoch: int | None = None,
) -> AuthResilienceState:
    """Clear retry counters while retaining the approved IP fingerprint."""
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    return AuthResilienceState(
        public_ip_sha256=state.public_ip_sha256,
        public_ip_changed=False,
        updated_at_epoch=now,
    )


def observe_public_ip_fingerprint(
    state: AuthResilienceState,
    fingerprint: str,
    *,
    now_epoch: int | None = None,
) -> AuthResilienceState:
    """Baseline the first hash and fail closed when a later hash differs."""
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    if len(fingerprint) != 64:
        raise ValueError("public IP fingerprint is invalid")
    changed = bool(
        state.public_ip_sha256 and state.public_ip_sha256 != fingerprint
    )
    return AuthResilienceState(
        attempt=state.attempt,
        retry_at_epoch=state.retry_at_epoch,
        public_ip_sha256=(
            state.public_ip_sha256 if changed else fingerprint
        ),
        public_ip_changed=state.public_ip_changed or changed,
        updated_at_epoch=now,
    )


def accept_public_ip_fingerprint(
    state: AuthResilienceState,
    fingerprint: str,
    *,
    now_epoch: int | None = None,
) -> AuthResilienceState:
    """Explicitly approve a hash after the operator updates the whitelist."""
    if len(fingerprint) != 64:
        raise ValueError("public IP fingerprint is invalid")
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    return AuthResilienceState(
        public_ip_sha256=fingerprint,
        updated_at_epoch=now,
    )
