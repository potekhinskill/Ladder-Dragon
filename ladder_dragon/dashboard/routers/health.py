# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: declare the host-health route group.

"""Health router extracted incrementally from the compatibility runtime."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])
