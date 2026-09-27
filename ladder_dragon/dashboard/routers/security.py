# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the existing dashboard access boundary.

from fastapi import APIRouter
from ladder_dragon.dashboard.security_dependencies import SecurityRouteState


def build_security_router(state: SecurityRouteState) -> APIRouter:
    router = APIRouter()

    @router.get('/api/security/csrf')
    def csrf_token():
        """Return a process-local token only to an authenticated same-origin client."""
        return {'ok': True, 'csrf_token': state.DASHBOARD_CSRF_TOKEN}

    return router
