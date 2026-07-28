# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the historical ASGI import while delegating to the package.

"""Compatibility ASGI facade for the Ladder Dragon dashboard."""

import sys

from ladder_dragon.dashboard import runtime as _runtime


sys.modules[__name__] = _runtime
