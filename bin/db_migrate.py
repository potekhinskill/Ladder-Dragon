#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run packaged SQLite migrations from the operator CLI.
"""SQLite migration command."""

import time

from ladder_dragon.persistence.migrations import main


if __name__ == "__main__":
    started = time.monotonic()
    result = main()
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    print(f"[STARTUP-TIMING] phase=migration elapsed_ms={duration_ms}", flush=True)
    raise SystemExit(result)
