# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose the packaged dashboard ASGI application.

"""Ladder Dragon dashboard ASGI entry point."""

from ladder_dragon.dashboard.runtime import app

__all__ = ["app"]
