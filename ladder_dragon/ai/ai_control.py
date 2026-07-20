# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the ai control component of the ai layer.
"""Ladder Dragon ai control support."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
AI_MODES = {"DISABLED", "SHADOW", "APPLY"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AI_CONTROL_FILE = Path("FastAPI/pi-dashboard/data/ai_control.json")


def resolve_ai_control_path(value: str | Path | None = None) -> Path:
    """Resolve one canonical control path independently of process cwd."""
    candidate = Path(value) if value else DEFAULT_AI_CONTROL_FILE
    if candidate.is_absolute():
        return candidate
    return (PROJECT_ROOT / candidate).resolve()


def utc_now_iso() -> str:
    """Handle utc now iso."""
    return datetime.now(timezone.utc).isoformat()


def write_ai_control(path: str | Path, *, enabled: bool, mode: str) -> dict[str, Any]:
    """Write ai control."""
    if not isinstance(enabled, bool):
        raise ValueError("AI control enabled must be boolean")
    normalized_mode = str(mode).strip().upper()
    if normalized_mode not in AI_MODES:
        raise ValueError("AI control mode must be DISABLED, SHADOW or APPLY")
    if not enabled:
        normalized_mode = "DISABLED"

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "enabled": enabled,
        "mode": normalized_mode,
        "updated_at": utc_now_iso(),
    }
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(document, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return document


def read_ai_control(path: str | Path) -> dict[str, Any] | None:
    """Read ai control."""
    target = Path(path)
    if not target.exists():
        return None
    with target.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError("AI control must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported AI control schema")
    if not isinstance(document.get("enabled"), bool):
        raise ValueError("AI control enabled must be boolean")
    mode = str(document.get("mode", "")).upper()
    if mode not in AI_MODES:
        raise ValueError("AI control mode is invalid")
    if not document["enabled"] and mode != "DISABLED":
        raise ValueError("disabled AI control must use DISABLED mode")
    if document["enabled"] and mode == "DISABLED":
        raise ValueError("enabled AI control must use SHADOW or APPLY mode")
    document["mode"] = mode
    return document
