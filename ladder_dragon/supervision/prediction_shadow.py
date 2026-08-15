# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: read sanitized executor state used only by prediction shadow telemetry.

"""Prediction-shadow evidence readers that never change an execution plan."""

import json
import os
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Sequence

from ladder_dragon.ai.ai_knowledge import KnowledgeStore
from ladder_dragon.strategy.prediction.experiments import (
    build_shadow_variants,
    record_shadow_variants,
    shadow_variant_report,
)
from ladder_dragon.strategy.prediction.experiment_config import (
    experiment_spec_for_generation,
    experiment_spec_for_symbol,
)
from ladder_dragon.strategy.prediction.models import PredictionFeatures, TradePlan
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


_EXPERIMENT_REPORT_CACHE: dict[
    str, tuple[float, dict[str, object]]
] = {}
_EXPERIMENT_LAST_RECORD: dict[str, float] = {}


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


def collect_shadow_experiments(
    store: PredictionShadowStore,
    *,
    symbol: str,
    features: PredictionFeatures,
    market_price: Decimal,
    baseline_plan: TradePlan,
    required_edge_pct: Decimal | None,
    record_interval_sec: int = 300,
    report_interval_sec: int = 900,
) -> dict[str, object]:
    """Record parallel variants and periodically refresh their expensive gates."""
    if required_edge_pct is None:
        return {
            "mode": "SHADOW",
            "available": False,
            "reason": "authoritative required edge is unavailable",
            "can_change_orders": False,
        }
    spec = experiment_spec_for_symbol(symbol)
    variants = build_shadow_variants(
        market_price=market_price,
        baseline_plan=baseline_plan,
        required_edge_pct=required_edge_pct,
        regime=features.regime,
        generation=spec.generation,
        symbol=symbol,
    )
    cache_key = f"{symbol.upper()}:{spec.generation}"
    now = time.monotonic()
    last_record = _EXPERIMENT_LAST_RECORD.get(cache_key)
    if (
        last_record is None
        or now < last_record
        or now - last_record >= max(60, record_interval_sec)
    ):
        record_shadow_variants(
            store,
            symbol=symbol,
            features=features,
            variants=variants,
            generation=spec.generation,
            horizons_min=spec.horizons_min,
        )
        _EXPERIMENT_LAST_RECORD[cache_key] = now
    cached = _EXPERIMENT_REPORT_CACHE.get(cache_key)
    if cached is not None and now - cached[0] < max(60, report_interval_sec):
        return cached[1]
    report = shadow_variant_report(
        store,
        symbol=symbol,
        variants=variants,
        before_ts_ms=features.snapshot_ts_ms,
        generation=spec.generation,
        horizons_min=spec.horizons_min,
        superseded_selection_generations=(
            spec.superseded_selection_generations
        ),
    )
    report["lifecycle_status"] = "SELECTION"
    superseded_reports = {}
    for generation in spec.superseded_selection_generations:
        historical_spec = experiment_spec_for_generation(
            generation, symbol=symbol
        )
        historical_variants = build_shadow_variants(
            market_price=market_price,
            baseline_plan=baseline_plan,
            required_edge_pct=required_edge_pct,
            regime=features.regime,
            generation=generation,
            symbol=symbol,
        )
        historical_report = shadow_variant_report(
            store,
            symbol=symbol,
            variants=historical_variants,
            before_ts_ms=features.snapshot_ts_ms,
            generation=generation,
            horizons_min=historical_spec.horizons_min,
        )
        historical_report["lifecycle_status"] = "SUPERSEDED"
        superseded_reports[generation] = historical_report
    report["superseded_reports"] = superseded_reports
    _EXPERIMENT_REPORT_CACHE[cache_key] = (now, report)
    return report


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


def blocked_plan_summary(
    symbol: str,
    ladder: Sequence[float],
    *,
    best_buy: float,
) -> str:
    """Describe a blocked plan compactly without dumping every ladder level."""
    return (
        f"[BLOCKED-SHADOW] {symbol} advisory snapshot "
        f"levels={len(ladder)} best_buy={best_buy:.2f} "
        f"range={min(ladder):.2f}..{max(ladder):.2f}; "
        "order mutation disabled"
    )


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
