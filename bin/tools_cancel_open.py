#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the safeguarded open-order cancellation CLI.

"""Explicit operator cancellation command."""

from ladder_dragon.execution.operator.cancel_open import main


if __name__ == "__main__":
    raise SystemExit(main())
