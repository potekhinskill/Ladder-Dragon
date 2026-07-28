#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: start the packaged supervisor from the operator CLI.
"""Ladder Dragon supervisor command."""

from __future__ import annotations

from ladder_dragon.supervision.runtime import main


if __name__ == "__main__":
    raise SystemExit(main())
