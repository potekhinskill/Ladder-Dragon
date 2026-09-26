# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own execution authority source checks without changing safety contracts.
"""Execution authority_command implementation."""

from __future__ import annotations

import json
from pathlib import Path

from ladder_dragon.verification.authority_paths import audit_execution_authority_paths


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    report = audit_execution_authority_paths(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2
