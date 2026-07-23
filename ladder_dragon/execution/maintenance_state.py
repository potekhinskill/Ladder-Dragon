# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: persist an explicit operator-owned trading maintenance state.
"""Distinguish an intentional stop from a failed trading process."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import time


SCHEMA_VERSION = 1
DEFAULT_PATH = Path("/var/lib/ladder-dragon/maintenance.json")
_SAFE_REASON = re.compile(r"^[A-Za-z0-9 .,;:_/+()'-]{1,160}$")


@dataclass(frozen=True)
class MaintenanceState:
    active: bool = False
    reason: str = ""
    updated_at_epoch: int = 0


def load_maintenance_state(path: str | Path = DEFAULT_PATH) -> MaintenanceState:
    target = Path(path)
    if not target.exists():
        return MaintenanceState()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("maintenance state schema is invalid")
    active = payload.get("active")
    reason = str(payload.get("reason") or "")
    updated = int(payload.get("updated_at_epoch", 0))
    if not isinstance(active, bool) or updated < 0:
        raise ValueError("maintenance state fields are invalid")
    if reason and not _SAFE_REASON.fullmatch(reason):
        raise ValueError("maintenance reason is invalid")
    return MaintenanceState(active=active, reason=reason, updated_at_epoch=updated)


def save_maintenance_state(
    path: str | Path,
    state: MaintenanceState,
) -> None:
    target = Path(path)
    if state.reason and not _SAFE_REASON.fullmatch(state.reason):
        raise ValueError("maintenance reason is invalid")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, **asdict(state)}
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=str(target.parent), text=True
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o644)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def set_maintenance(
    path: str | Path,
    reason: str,
    *,
    now_epoch: int | None = None,
) -> MaintenanceState:
    normalized = reason.strip()
    if not _SAFE_REASON.fullmatch(normalized):
        raise ValueError("maintenance reason is invalid")
    state = MaintenanceState(
        active=True,
        reason=normalized,
        updated_at_epoch=(
            int(time.time()) if now_epoch is None else int(now_epoch)
        ),
    )
    save_maintenance_state(path, state)
    return state


def clear_maintenance(
    path: str | Path,
    *,
    now_epoch: int | None = None,
) -> MaintenanceState:
    state = MaintenanceState(
        active=False,
        reason="",
        updated_at_epoch=(
            int(time.time()) if now_epoch is None else int(now_epoch)
        ),
    )
    save_maintenance_state(path, state)
    return state
