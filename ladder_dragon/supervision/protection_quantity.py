# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: retain the supervisor import for shared quantity evidence.
"""Compatibility import for shared protection quantity evidence."""

from ladder_dragon.execution.protection_quantity import quantity, require_order_id, verify_quantities

__all__ = ["quantity", "require_order_id", "verify_quantities"]
