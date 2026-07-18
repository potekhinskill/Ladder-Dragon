# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: implement the ai runtime status component of the ai layer.
"""Безопасный обмен runtime-статусом между торговым процессом и дашбордом."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    """Вернуть UTC-время в стабильном ISO-формате."""
    return datetime.now(timezone.utc).isoformat()


def write_runtime_status(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Атомарно записать JSON со строгими правами без частично видимого файла."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": SCHEMA_VERSION,
        **dict(payload),
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


def read_runtime_status(path: str | Path) -> dict[str, Any]:
    """Прочитать status-файл; повреждённый или несовместимый файл отвергается."""
    with Path(path).open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError("runtime status must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported runtime status schema")
    return document
