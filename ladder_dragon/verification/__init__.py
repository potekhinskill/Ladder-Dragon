# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose the fail-closed verification harness contract.
"""Unified verification harness for local, release and venue checks."""

from .models import CheckResult, HarnessReport, Status
from .runner import HarnessRunner

__all__ = ["CheckResult", "HarnessReport", "HarnessRunner", "Status"]
