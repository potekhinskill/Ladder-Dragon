# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the historical AI-context import while delegating to its package.

"""Compatibility facade for AI context services."""

import sys

from ladder_dragon.ai.context import runtime as _runtime

sys.modules[__name__] = _runtime
