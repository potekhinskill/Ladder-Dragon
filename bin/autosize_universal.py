#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the historical worker CLI while delegating to the package.

"""Compatibility entry point for the Ladder Dragon execution worker."""

import sys

from ladder_dragon.execution.worker import runtime as _runtime


if __name__ == "__main__":
    raise SystemExit(_runtime.main())

sys.modules[__name__] = _runtime
