#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose strict replay validation across separate source sessions.
"""CLI compatibility wrapper for replay session validation."""

from ladder_dragon.verification.replay_sessions import main


if __name__ == "__main__":
    raise SystemExit(main())
