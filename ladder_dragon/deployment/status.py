# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: publish bounded deployment evidence and an operator notice.
"""Publish bounded deployment evidence and an optional operator notice."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from ladder_dragon.execution.telegram_alerts import send_message


DEFAULT_STATUS_PATH = Path("/var/lib/ladder-dragon/deployment-status.json")
MAX_STATUS_BYTES = 4096
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_STATE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _status_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return Path(os.getenv("LADDER_DRAGON_DEPLOYMENT_STATUS_FILE", str(DEFAULT_STATUS_PATH)))


def read_deployment_status(path: Path | None = None) -> dict[str, Any] | None:
    """Read validated, bounded deployment evidence."""
    target = _status_path(path)
    try:
        with target.open("rb") as stream:
            raw = stream.read(MAX_STATUS_BYTES + 1)
    except OSError:
        return None
    if not raw or len(raw) > MAX_STATUS_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != 1 or payload.get("status") != "PASS":
        return None
    commit = str(payload.get("commit") or "").lower()
    version = str(payload.get("version") or "")
    runtime_state = str(payload.get("runtime_state") or "UNKNOWN")
    if not _SHA_RE.fullmatch(commit) or not _VERSION_RE.fullmatch(version):
        return None
    if not _STATE_RE.fullmatch(runtime_state):
        return None
    if payload.get("dashboard_backend_ready") is not True:
        return None
    if payload.get("sqlite_ready") is not True:
        return None
    return {
        "schema_version": 1,
        "status": "PASS",
        "commit": commit,
        "version": version,
        "completed_at": str(payload.get("completed_at") or ""),
        "dashboard_backend_ready": True,
        "sqlite_ready": True,
        "runtime_state": runtime_state,
    }


def write_deployment_status(
    *,
    commit: str,
    version: str,
    runtime_state: str,
    path: Path | None = None,
) -> dict[str, Any]:
    """Replace the single derived deployment record atomically."""
    normalized_commit = commit.strip().lower()
    normalized_version = version.strip()
    if not _SHA_RE.fullmatch(normalized_commit):
        raise ValueError("commit must be an exact 40-character SHA")
    if not _VERSION_RE.fullmatch(normalized_version):
        raise ValueError("version must use three numeric components")
    normalized_state = str(runtime_state or "UNKNOWN").strip().upper()
    if not _STATE_RE.fullmatch(normalized_state):
        raise ValueError("runtime state has an invalid format")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "PASS",
        "commit": normalized_commit,
        "version": normalized_version,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_backend_ready": True,
        "sqlite_ready": True,
        "runtime_state": normalized_state,
    }
    target = _status_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_STATUS_BYTES:
        raise ValueError("deployment status exceeds its size limit")
    try:
        temporary.write_bytes(encoded)
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
    return payload


def deployment_message(status: Mapping[str, Any]) -> str | None:
    """Build the English Telegram notice for a verified IP block."""
    if status.get("runtime_state") != "IP_BLOCKED":
        return None
    return (
        "Ladder Dragon: update complete\n"
        "Dashboard backend and SQLite readiness checks passed.\n"
        "Trading is IP_BLOCKED because the public IP changed.\n"
        "Review the Binance whitelist.\n"
        "New BUY orders and trading mutations are blocked.\n"
        "Healthy local dashboard sections remain available."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish verified deployment status")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--runtime-state", required=True)
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args()
    status = write_deployment_status(
        commit=args.commit,
        version=args.version,
        runtime_state=args.runtime_state,
        path=args.status_file,
    )
    message = deployment_message(status)
    if message is not None and not send_message(message):
        print("[WARN] verified deployment notice was not delivered", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
