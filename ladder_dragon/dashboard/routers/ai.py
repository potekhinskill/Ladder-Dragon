# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: declare the AI telemetry and control route group.

"""AI router extracted incrementally from the compatibility runtime."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/ai", tags=["ai"])
