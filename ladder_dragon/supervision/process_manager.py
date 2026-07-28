# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: calculate and persist bounded child-process restart schedules.

"""Child-process lifecycle policy separated from subprocess orchestration."""

import os
import subprocess
import time
from collections.abc import Callable, MutableMapping
from typing import Any


def schedule_child_restart(
    symbol: str,
    return_code: int,
    runtime_sec: float,
    *,
    failures: MutableMapping[str, int],
    restart_after: MutableMapping[str, float],
    now: float | None = None,
) -> float:
    """Record an exponential, bounded restart delay for one child."""
    current = time.time() if now is None else now
    stable_sec = max(1, int(os.getenv("BOT_CHILD_STABLE_SEC", "30")))
    if return_code != 0 and runtime_sec < stable_sec:
        failure_count = failures.get(symbol, 0) + 1
        failures[symbol] = failure_count
        base = max(1, int(os.getenv("BOT_CHILD_RESTART_BASE_SEC", "2")))
        maximum = max(
            base,
            int(os.getenv("BOT_CHILD_RESTART_MAX_SEC", "60")),
        )
        delay = float(min(maximum, base * (2 ** min(failure_count - 1, 10))))
    else:
        failures[symbol] = 0
        delay = 0.0
    restart_after[symbol] = current + delay
    return delay


def stop_child(
    symbol: str,
    reason: str,
    *,
    processes: MutableMapping[str, Any],
    started_at: MutableMapping[str, float],
    restart_after: MutableMapping[str, float],
    failures: MutableMapping[str, int],
    logger: Callable[[str], None],
) -> bool:
    """Gracefully stop one managed child and clear its lifecycle state."""
    process = processes.get(symbol)
    if process is None:
        return True
    stopped = False
    try:
        if process.poll() is None:
            logger(
                f"[RISK] stop child {symbol} pid={process.pid}: {reason}"
            )
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger(
                    f"[RISK] kill unresponsive child {symbol} "
                    f"pid={process.pid}"
                )
                process.kill()
                process.wait(timeout=2)
        else:
            process.wait(timeout=0)
        stopped = process.poll() is not None
    except (OSError, subprocess.SubprocessError) as exc:
        logger(
            f"[RISK] child cleanup failed {symbol} "
            f"pid={process.pid}: {exc}"
        )
    if stopped:
        processes.pop(symbol, None)
        started_at.pop(symbol, None)
        restart_after.pop(symbol, None)
        failures.pop(symbol, None)
    return stopped
