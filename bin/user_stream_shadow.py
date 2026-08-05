#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run the notification-only account-stream soak service.
"""CLI for the independent read-only User Data Stream observer."""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
import threading

from ladder_dragon.execution.user_stream_shadow import (
    UserStreamShadowConfig,
    run_user_stream_shadow,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path(
            "/var/lib/ladder-dragon/user-stream/user_stream_SOLUSDT.json"
        ),
    )
    parser.add_argument("--rest-poll-sec", type=float, default=60.0)
    args = parser.parse_args()

    stop_event = threading.Event()
    reconnect_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    def request_reconnect(_signum: int, _frame: object) -> None:
        # The main loop performs the socket operation outside the signal handler.
        reconnect_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGUSR1, request_reconnect)
    return run_user_stream_shadow(
        UserStreamShadowConfig(
            symbol=str(args.symbol).upper(),
            state_path=args.state_path,
            rest_poll_sec=args.rest_poll_sec,
        ),
        stop_event=stop_event,
        reconnect_event=reconnect_event,
        logger=lambda message: print(message, flush=True),
    )


if __name__ == "__main__":
    raise SystemExit(main())
