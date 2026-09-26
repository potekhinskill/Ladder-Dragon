# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own one daily digest boundary without changing accounting behavior.
"""Daily digest state ownership."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _last_sent(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("report_date", ""))


def _last_alert(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("blocked_alert_date", ""))


def _mark_state(
    path: Path,
    *,
    report_date: str | None = None,
    blocked_alert_date: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        payload = {}
    if report_date is not None:
        payload["report_date"] = report_date
    if blocked_alert_date is not None:
        payload["blocked_alert_date"] = blocked_alert_date
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)
