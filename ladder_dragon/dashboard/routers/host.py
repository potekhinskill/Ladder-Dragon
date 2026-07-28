# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: declare the host telemetry route group.

"""Host router extracted incrementally from the compatibility runtime."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["host"])
