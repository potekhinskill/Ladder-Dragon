#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the historical supervisor command and import path.
"""Compatibility alias for the packaged supervisor runtime."""

from __future__ import annotations

import sys

from ladder_dragon.supervision import runtime as _runtime


if __name__ == "__main__":
    raise SystemExit(_runtime.main())

# Importers must receive the implementation module itself. This preserves
# monkeypatching of process state and safety dependencies at the historical
# ``bin.ai_supervisor`` path while keeping production logic out of ``bin``.
sys.modules[__name__] = _runtime
