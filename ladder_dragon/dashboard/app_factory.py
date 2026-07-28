# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: construct the read-only dashboard ASGI application.

"""Dashboard application factory."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import FastAPI


def create_dashboard_app(
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]],
) -> FastAPI:
    """Create a non-introspectable local health API."""
    return FastAPI(
        title="Pi Health API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
