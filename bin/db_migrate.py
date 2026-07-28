#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run packaged SQLite migrations from the operator CLI.
"""SQLite migration command."""

from ladder_dragon.persistence.migrations import main


if __name__ == "__main__":
    raise SystemExit(main())
