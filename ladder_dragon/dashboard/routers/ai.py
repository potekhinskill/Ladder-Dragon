# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve AI-status presentation through explicit component ownership.

import sqlite3
from pathlib import Path
from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from ladder_dragon.dashboard.ai_dependencies import AiRouteState
from ladder_dragon.dashboard.ai_status_context import runtime_context
from ladder_dragon.dashboard.ai_status_reader import read_ai_decisions
from ladder_dragon.dashboard.ai_status_policy import policy_summary


def build_ai_router(deps: AiRouteState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/ai/status")
    def ai_status(limit: int = 50):
        """Handle ai status."""
        limit = max(1, min(int(limit), 200))
        runtime = deps._load_ai_runtime_status()
        (runtime_ai, runtime_budgets, runtime_age_sec, runtime_stale,
         effective_mode) = runtime_context(deps, runtime)
        db_path = deps._runtime_data_path(runtime, "ai_decisions_db", deps.AI_DECISIONS_DB)
        try:
            recent, knowledge_stats = read_ai_decisions(deps, db_path, limit)
        except sqlite3.Error as exc:
            print(f"[DASHBOARD] AI_DB_READ_FAILED type={type(exc).__name__}", flush=True)
            return JSONResponse({"ok": False, "error": "AI_DB_READ_FAILED"}, status_code=503)
        usage_path = deps._runtime_data_path(runtime, "ai_usage_log", deps.AI_USAGE_LOG)
        usage = deps._ai_usage_today(usage_path)
        def _file_age(path: Path) -> Optional[int]:
            try:
                return max(0, int(deps.time.time() - path.stat().st_mtime))
            except OSError:
                return None
        (request_limit, token_limit, cost_limit, budget_exhausted,
         degraded_reasons, state) = policy_summary(
            deps, runtime, runtime_budgets, runtime_stale, effective_mode, usage, recent,
        )
        edge_values = [
            int(
                (row.get("recommended_mode") == "UP" and row["return_1h"] > .001)
                or (row.get("recommended_mode") == "DOWN" and row["return_1h"] < -.001)
                or (row.get("recommended_mode") == "FLAT" and abs(row["return_1h"]) <= .001)
            ) - int(
                (row.get("baseline_mode") == "UP" and row["return_1h"] > .001)
                or (row.get("baseline_mode") == "DOWN" and row["return_1h"] < -.001)
                or (row.get("baseline_mode") == "FLAT" and abs(row["return_1h"]) <= .001)
            )
            for row in recent if row.get("return_1h") is not None
        ]
        return {
            "ok": True,
            "mode": effective_mode,
            "state": state,
            "runtime": {
                "connected": bool(runtime),
                "stale": runtime_stale,
                "age_sec": runtime_age_sec,
                "process_state": runtime.get("state"),
                "updated_at": runtime.get("updated_at"),
                "venue": runtime.get("venue"),
                "execution_mode": runtime.get("execution_mode"),
                "auth_backoff": runtime.get("auth_backoff"),
                "ip_guard": runtime.get("ip_guard"),
                "recovery": runtime.get("recovery"),
                "provider": runtime_ai.get("provider"),
                "model": runtime_ai.get("model"),
                # Publish only numeric policy limits. The dashboard must not read
                # the bot's private .env or maintain a second configuration copy.
                "budgets": {
                    "max_requests_per_day": request_limit,
                    "max_tokens_per_day": token_limit,
                    "max_cost_usd_per_day": str(cost_limit),
                },
                "product": runtime.get("product"),
                "last_decision": runtime.get("last_decision"),
            },
            "data_sources": {
                "follow_bot_paths": deps.DASHBOARD_FOLLOW_BOT_PATHS,
                "decisions_db": str(db_path),
                "usage_log": str(usage_path),
                "decision_db_age_sec": _file_age(db_path),
                "usage_log_age_sec": _file_age(usage_path),
                "context_age_sec": runtime_age_sec,
            },
            "knowledge_base": knowledge_stats,
            "usage_today": usage,
            "budget_exhausted": budget_exhausted,
            "degraded_reasons": degraded_reasons,
            "recent": recent,
            "applied_count": sum(bool(row.get("applied")) for row in recent),
            "changed_mode_count": sum(
                row.get("recommended_mode") != row.get("baseline_mode")
                for row in recent
            ),
            "calibration_1h": deps._ai_calibration(recent),
            "ai_vs_baseline_1h": {
                "samples": len(edge_values),
                "edge": sum(edge_values) / len(edge_values) if edge_values else 0,
            },
        }

    return router
