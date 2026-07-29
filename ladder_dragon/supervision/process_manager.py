# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: calculate and persist bounded child-process restart schedules.

"""Child-process lifecycle policy separated from subprocess orchestration."""

import os
import signal
import subprocess
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any


class SupervisorShutdownSignal:
    """Route the first SIGTERM through the supervisor's graceful exit path."""

    def __init__(self) -> None:
        self.requested = False
        self._previous: Any = None

    def install(self) -> None:
        self.requested = False
        self._previous = signal.signal(signal.SIGTERM, self)

    def restore(self) -> None:
        signal.signal(signal.SIGTERM, self._previous)

    def __call__(self, _signum: int, _frame: object) -> None:
        if self.requested:
            return
        self.requested = True
        raise KeyboardInterrupt


@dataclass
class ChildProcessRegistry:
    """Bind child lifecycle policy to the supervisor's mutable registries."""

    processes: MutableMapping[str, Any]
    started_at: MutableMapping[str, float]
    restart_after: MutableMapping[str, float]
    failures: MutableMapping[str, int]
    restart_history: MutableMapping[str, list[float]]

    def schedule(
        self,
        symbol: str,
        return_code: int,
        runtime_sec: float,
        *,
        logger: Callable[[str], None],
        notifier: Callable[[str, list[str], dict[str, object]], object],
        now: float | None = None,
    ) -> float:
        return schedule_child_restart(
            symbol,
            return_code,
            runtime_sec,
            failures=self.failures,
            restart_after=self.restart_after,
            restart_history=self.restart_history,
            logger=logger,
            notifier=notifier,
            now=now,
        )

    def stop(self, symbol: str, reason: str, logger: Callable[[str], None]) -> bool:
        return stop_child(
            symbol,
            reason,
            processes=self.processes,
            started_at=self.started_at,
            restart_after=self.restart_after,
            failures=self.failures,
            restart_history=self.restart_history,
            logger=logger,
        )

    def stop_all(self, reason: str, logger: Callable[[str], None]) -> bool:
        return stop_children(
            reason,
            processes=self.processes,
            started_at=self.started_at,
            restart_after=self.restart_after,
            failures=self.failures,
            restart_history=self.restart_history,
            logger=logger,
        )


def schedule_child_restart(
    symbol: str,
    return_code: int,
    runtime_sec: float,
    *,
    failures: MutableMapping[str, int],
    restart_after: MutableMapping[str, float],
    restart_history: MutableMapping[str, list[float]],
    logger: Callable[[str], None] | None = None,
    notifier: Callable[[str, list[str], dict[str, object]], object] | None = None,
    now: float | None = None,
) -> float:
    """Record a bounded restart delay using rapid-failure and window evidence."""
    current = time.time() if now is None else now
    stable_sec = max(1, int(os.getenv("BOT_CHILD_STABLE_SEC", "30")))
    window_sec = max(
        60, int(os.getenv("BOT_CHILD_RESTART_WINDOW_SEC", "3600"))
    )
    window_limit = max(
        1, int(os.getenv("BOT_CHILD_RESTART_WINDOW_LIMIT", "3"))
    )
    alert_count = max(
        window_limit,
        int(os.getenv("BOT_CHILD_RESTART_ALERT_COUNT", "5")),
    )
    history = [
        timestamp
        for timestamp in restart_history.get(symbol, [])
        if current - timestamp <= window_sec
    ]
    if return_code != 0:
        history.append(current)
    restart_history[symbol] = history
    window_failure = return_code != 0 and len(history) >= window_limit
    rapid_failure = return_code != 0 and runtime_sec < stable_sec
    if rapid_failure or window_failure:
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
    if (
        return_code != 0
        and len(history) == alert_count
    ):
        if logger is not None:
            logger(
                f"[CHILD-RESTART-STORM] {symbol} restarts={len(history)} "
                f"window_sec={window_sec}"
            )
        if notifier is not None:
            notifier(
                "worker restart storm",
                [f"{symbol} exited {len(history)} times in the restart window"],
                {
                    "symbol": symbol,
                    "restarts": len(history),
                    "window_sec": window_sec,
                },
            )
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
    restart_history: MutableMapping[str, list[float]] | None = None,
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
        if restart_history is not None:
            restart_history.pop(symbol, None)
    return stopped


def stop_children(
    reason: str,
    *,
    processes: MutableMapping[str, Any],
    started_at: MutableMapping[str, float],
    restart_after: MutableMapping[str, float],
    failures: MutableMapping[str, int],
    restart_history: MutableMapping[str, list[float]],
    logger: Callable[[str], None],
) -> bool:
    """Stop all registered children and retain every unconfirmed process."""
    stopped = True
    for symbol in list(processes):
        stopped = stop_child(
            symbol,
            reason,
            processes=processes,
            started_at=started_at,
            restart_after=restart_after,
            failures=failures,
            restart_history=restart_history,
            logger=logger,
        ) and stopped
    if not stopped:
        logger("[CHILD-STOP-INCOMPLETE] one or more workers remain registered")
    return stopped
