# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the ai control component of the ai layer.
"""Безопасный runtime-переключатель рекомендательного AI-слоя.

Файл управления намеренно отделён от telemetry status: дашборд может менять
только флаг включения, а торговый процесс сам применяет допустимый режим,
сохраняя все проверки Policy/Risk Manager.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
AI_MODES = {"DISABLED", "SHADOW", "APPLY"}


def utc_now_iso() -> str:
    """Вернуть UTC-время для аудита изменения переключателя."""
    return datetime.now(timezone.utc).isoformat()


def write_ai_control(path: str | Path, *, enabled: bool, mode: str) -> dict[str, Any]:
    """Атомарно записать строгий и минимальный control-файл с правами 0600."""
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
    """Прочитать control-файл; отсутствие файла означает отсутствие override."""
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
