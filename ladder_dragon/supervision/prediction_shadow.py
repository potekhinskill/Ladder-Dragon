# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: read sanitized executor state used only by prediction shadow telemetry.

"""Prediction-shadow evidence readers that never change an execution plan."""

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict

from ladder_dragon.ai.ai_knowledge import KnowledgeStore


def build_knowledge_store(
    decisions_db: str,
    *,
    getenv: Callable[[str, str], str] = os.getenv,
) -> KnowledgeStore:
    """Build the bounded RAG store from validated supervisor settings."""
    return KnowledgeStore(
        decisions_db,
        retention_days=int(
            getenv("AI_RAG_RETENTION_DAYS", "365") or 365
        ),
        candidate_limit=int(
            getenv("AI_RAG_CANDIDATE_LIMIT", "1000") or 1000
        ),
    )


def publish_plan_decision_status(
    last_decision: Dict[str, Any],
    *,
    execution_allowed: bool,
    publish: Callable[..., None],
) -> None:
    """Publish advisory evidence without masking a fail-closed runtime state."""
    updates: Dict[str, Any] = {"last_decision": last_decision}
    if execution_allowed:
        updates["state"] = "RUNNING"
    publish(**updates)


def prediction_panic_state(
    symbol: str,
    *,
    run_dir: str | None = None,
) -> tuple[bool | None, int | None]:
    """Read only the executor's sanitized PANIC state."""
    safe_symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,20}", safe_symbol):
        return None, None
    root = run_dir if run_dir is not None else os.getenv("BOT_RUN_DIR", "/run/mybot")
    path = Path(root) / f"panic_state_{safe_symbol}.json"
    try:
        if not path.is_file() or path.stat().st_size > 16_384:
            return None, None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or int(payload.get("schema_version", 0)) != 1
            or not isinstance(payload.get("on"), bool)
        ):
            return None, None
        hits = int(payload.get("hits", 0) or 0)
        if not 0 <= hits <= 1_000_000:
            return None, None
        return bool(payload["on"]), hits
    except (
        OSError,
        TypeError,
        ValueError,
        OverflowError,
        json.JSONDecodeError,
    ):
        return None, None
