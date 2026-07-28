#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the historical database migration command path.
"""Compatibility CLI for packaged SQLite migrations."""

from ladder_dragon.persistence.migrations import MIGRATIONS, main, migrate

__all__ = ["MIGRATIONS", "main", "migrate"]


if __name__ == "__main__":
    raise SystemExit(main())
