# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose filled-BUY protection operations.

"""Filled-BUY protection API."""

from ladder_dragon.execution.protection.runtime import protect_filled_buys

__all__ = ["protect_filled_buys"]
