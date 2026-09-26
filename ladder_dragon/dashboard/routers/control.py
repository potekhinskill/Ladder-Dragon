# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own advisory-control HTTP handlers without new authority.
"""Advisory-control endpoints retain application authentication and CSRF."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from ladder_dragon.dashboard.control_dependencies import ControlRouteState
from ladder_dragon.dashboard.control_snapshot import control_snapshot


def build_control_router(state: ControlRouteState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/ai/control")
    def ai_control():
        """Handle ai control."""
        snapshot = control_snapshot(state)
        if snapshot["control_error"]:
            return JSONResponse(
                {"ok": False, "error": "AI control file is invalid", **snapshot},
                status_code=503,
            )
        return {"ok": True, **snapshot}

    @router.post("/api/ai/control")
    async def set_ai_control(request: Request):
        """Handle set ai control."""
        snapshot = control_snapshot(state)
        if not snapshot["configured"] or snapshot["configured_mode"] == "DISABLED":
            return JSONResponse(
                {"ok": False, "error": "AI advisor is not configured", **snapshot},
                status_code=409,
            )
        try:
            payload = await request.json()
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "JSON body is required"}, status_code=400)
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            return JSONResponse(
                {"ok": False, "error": "enabled must be boolean"}, status_code=400
            )
        try:
            document = state.write_ai_control(
                state.AI_CONTROL_FILE,
                enabled=payload["enabled"],
                mode=str(snapshot["configured_mode"]),
            )
        except (OSError, TypeError, ValueError) as exc:
            print(f"[DASHBOARD] AI_CONTROL_WRITE_FAILED type={type(exc).__name__}", flush=True)
            return JSONResponse({"ok": False, "error": "AI_CONTROL_WRITE_FAILED"}, status_code=503)
        return {
            "ok": True,
            "configured": True,
            "enabled": bool(document["enabled"]),
            "mode": document["mode"],
            "updated_at": document["updated_at"],
        }

    return router
