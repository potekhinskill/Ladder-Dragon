# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define recovery, schema and deployment release checks.
"""Release checks for durable recovery and deployment assets."""

from __future__ import annotations

from ladder_dragon.verification.models import CheckSpec, HarnessContext


def release_recovery_checks(context: HarnessContext) -> list[CheckSpec]:
    python = context.python
    return [
        CheckSpec(
            name="recovery_regression",
            argv=(
                python,
                "-m",
                "pytest",
                "tests/test_order_recovery.py",
                "tests/test_worker_order_recovery.py",
                "tests/test_safety_gates.py",
            ),
            timeout_sec=1200,
        ),
        CheckSpec(
            name="migration_deployment",
            argv=(
                python,
                "-m",
                "pytest",
                "tests/test_migrations.py",
                "tests/test_deploy_assets.py",
                "tests/test_deploy_config_parsers.py",
            ),
            timeout_sec=1200,
        ),
    ]
