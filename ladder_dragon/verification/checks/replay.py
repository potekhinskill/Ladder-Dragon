# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define replay, walk-forward and approval release checks.
"""Release checks for replay and statistical approval behavior."""

from __future__ import annotations

from ladder_dragon.verification.models import CheckSpec, HarnessContext


def release_replay_checks(context: HarnessContext) -> list[CheckSpec]:
    python = context.python
    return [
        CheckSpec(
            name="replay_regression",
            argv=(
                python,
                "-m",
                "pytest",
                "tests/test_market_replay.py",
                "tests/test_replay_validation.py",
                "tests/test_replay_readiness.py",
            ),
            timeout_sec=900,
        ),
        CheckSpec(
            name="walk_forward_approval",
            argv=(
                python,
                "-m",
                "pytest",
                "tests/test_simulation.py",
                "tests/test_prediction.py",
            ),
            timeout_sec=900,
        ),
    ]
