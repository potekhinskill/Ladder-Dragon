#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: keep the file role and safety boundaries clear during maintenance.
"""Комбинированный генератор VWAP окружения."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--with-autotune", action="store_true")
    parser.add_argument("--autotune-hours", type=int, default=24)
    parser.add_argument("--autotune-threshold", type=float, default=25.0)
    parser.add_argument("--autotune-state", type=str, default="/run/mybot/vwap_state.json")
    args = parser.parse_args()

    def env(name: str, default: str) -> str:
        return os.getenv(name, default)

    if os.getenv("VWAP_AUTOTUNE") is not None:
        args.with_autotune = os.getenv("VWAP_AUTOTUNE") not in ("0", "false", "False")
    args.autotune_hours = int(os.getenv("VWAP_AUTOTUNE_HOURS", str(args.autotune_hours)))
    args.autotune_threshold = float(os.getenv("VWAP_AUTOTUNE_THRESHOLD", str(args.autotune_threshold)))
    args.autotune_state = os.getenv("VWAP_AUTOTUNE_STATE", args.autotune_state)

    base_cmd = [
        "/home/bot/apps/binance_bot/.venv/bin/python3",
        str(Path(__file__).resolve().with_name("gen_vwap_env.py")),
        "--symbols", args.symbols,
        "--interval", env("BUY_VWAP_INTERVAL", "1m"),
        "--window", env("BUY_VWAP_WINDOW", "240"),
        "--base-premium", env("BUY_VWAP_PREMIUM", "0.0030"),
        "--base-discount", env("BUY_VWAP_DISCOUNT", "0.0060"),
        "--base-scale", env("BUY_VWAP_DISCOUNT_SCALE", "1.30"),
        "--premium-up-mult", env("BUY_VWAP_PREMIUM_UP_MULT", "0.75"),
        "--premium-down-mult", env("BUY_VWAP_PREMIUM_DOWN_MULT", "1.20"),
        "--premium-atr-coef", env("BUY_VWAP_PREMIUM_ATR_COEF", "0.0"),
        "--premium-floor", env("BUY_VWAP_PREMIUM_FLOOR", "0.0008"),
        "--premium-ceil", env("BUY_VWAP_PREMIUM_CEIL", "0.0060"),
        "--scale-atr-coef", env("BUY_VWAP_DISCOUNT_SCALE_ATR_COEF", "2.0"),
        "--scale-min", env("BUY_VWAP_DISCOUNT_SCALE_MIN", "1.0"),
        "--scale-max", env("BUY_VWAP_DISCOUNT_SCALE_MAX", "2.5"),
    ]

    base_out = subprocess.check_output(base_cmd, text=True)

    lines: List[str] = []
    lines.append(base_out.strip())

    if args.with_autotune:
        auto_cmd = [
            "/home/bot/apps/binance_bot/.venv/bin/python3",
            str(Path(__file__).resolve().with_name("gen_vwap_autotune.py")),
            "--symbols", args.symbols,
            "--hours", str(args.autotune_hours),
            "--pnl-threshold", str(args.autotune_threshold),
            "--state-file", args.autotune_state,
        ]
        auto_out = subprocess.check_output(auto_cmd, text=True)
        lines.append(auto_out.strip())

    with open(args.out, "a", encoding="utf-8") as fh:
        for line in lines:
            for sub in line.splitlines():
                if sub.strip():
                    fh.write(sub.strip() + "\n")


if __name__ == "__main__":
    main()
