#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run the packaged AI plan service from the operator CLI.
"""AI plan-runner command."""

from ladder_dragon.supervision.plan_runner import main


if __name__ == "__main__":
    raise SystemExit(main())
