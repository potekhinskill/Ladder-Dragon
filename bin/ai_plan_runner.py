#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the historical AI plan-runner command path.
"""Compatibility CLI for :mod:`ladder_dragon.supervision.plan_runner`."""

from ladder_dragon.supervision.plan_runner import (
    build_ladder_pct,
    main,
    parse_args,
)

__all__ = ["build_ladder_pct", "main", "parse_args"]


if __name__ == "__main__":
    raise SystemExit(main())
