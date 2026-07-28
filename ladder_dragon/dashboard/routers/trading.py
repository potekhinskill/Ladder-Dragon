# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: declare the read-only trading route group.

"""Trading router extracted incrementally from the compatibility runtime."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["trading"])
