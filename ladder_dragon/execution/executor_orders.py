# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the executor order API while delegating by order type.

"""Compatibility facade for order placement."""

import sys

from ladder_dragon.execution.orders import runtime as _runtime

sys.modules[__name__] = _runtime
