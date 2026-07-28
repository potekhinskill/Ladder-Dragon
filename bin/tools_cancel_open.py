#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the safeguarded open-order cancellation CLI.

"""Compatibility CLI for explicit operator cancellation."""

import sys

from ladder_dragon.execution.operator import cancel_open as _runtime


if __name__ == "__main__":
    raise SystemExit(_runtime.main())

sys.modules[__name__] = _runtime
