# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: start the packaged execution worker from the operator CLI.

"""Execution-worker bootstrap."""

from __future__ import annotations


def main() -> None:
    """Start one worker using the live runtime module namespace."""
    from ladder_dragon.execution.worker import runtime
    from ladder_dragon.execution.worker.lifecycle import (
        WorkerRuntimeState,
        run_worker,
    )

    return run_worker(WorkerRuntimeState(vars(runtime)))
