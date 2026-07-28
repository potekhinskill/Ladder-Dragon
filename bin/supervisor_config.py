# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve compatibility for supervisor configuration imports.
"""Compatibility facade for the packaged supervisor configuration."""

from ladder_dragon.supervision.config import (
    build_supervisor_parser,
    env_flag,
    validate_supervisor_args,
)

__all__ = [
    "build_supervisor_parser",
    "env_flag",
    "validate_supervisor_args",
]
