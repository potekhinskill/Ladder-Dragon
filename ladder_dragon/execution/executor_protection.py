# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the executor protection API while delegating to services.

"""Compatibility facade for position protection."""

import sys

from ladder_dragon.execution.protection import runtime as _runtime

sys.modules[__name__] = _runtime
