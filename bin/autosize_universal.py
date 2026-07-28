#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: start the packaged execution worker from the operator CLI.

"""Ladder Dragon execution-worker command."""

from ladder_dragon.execution.worker.bootstrap import main


if __name__ == "__main__":
    raise SystemExit(main())
