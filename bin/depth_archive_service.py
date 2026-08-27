#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run continuous public capture and bounded offline calibration.
"""Public-only capture service. No credentials or order capabilities are used."""

import argparse
from pathlib import Path
import signal
import threading

import requests
from websocket import WebSocketException

from ladder_dragon.strategy.depth_capture import capture_segments
from ladder_dragon.strategy.depth_processing import calibrate_segment, process_backlog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--duration-sec", type=int, default=3300)
    parser.add_argument("--max-events", type=int, default=250000)
    parser.add_argument("--capacity-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--calibrate", type=Path)
    parser.add_argument("--prediction-db", type=Path)
    args = parser.parse_args()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    worker = None
    try:
        if args.calibrate:
            calibrate_segment(args.calibrate)
            return 0
        if args.directory is None:
            parser.error("--directory is required for capture")
        args.directory.mkdir(parents=True, exist_ok=True)
        worker = threading.Thread(target=process_backlog, args=(args.directory, stop, args.prediction_db), daemon=True)
        worker.start()
        capture_segments(args.symbol, args.directory, duration_sec=args.duration_sec,
                         max_events=args.max_events, capacity_bytes=args.capacity_bytes,
                         max_segments=1 if args.once else 10000,
                         stop_requested=stop.is_set)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError,
            requests.RequestException, WebSocketException) as exc:
        print(f"[DEPTH-CAPTURE] status=BLOCKED error={type(exc).__name__}", flush=True)
        return 2
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=7)


if __name__ == "__main__":
    raise SystemExit(main())
