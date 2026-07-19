#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: parse service tuning as allowlisted data without shell evaluation.
"""Parse the root-owned service tuning arguments through a strict allowlist."""

from __future__ import annotations

import shlex
import sys
from decimal import Decimal, InvalidOperation


VALUE_OPTIONS = {
    "--cap-floor-usdt",
    "--cap-ceil-usdt",
    "--target-buy-per-symbol",
    "--grid-density",
    "--near-ttl-sec",
    "--far-ttl-sec",
    "--interval-seconds",
    "--child-loop-minutes",
    "--max-oco-per-symbol",
    "--risk-check-sec",
}
FLAG_OPTIONS = {
    "--smart-rolling",
}


def parse_extra_args(raw: str) -> list[str]:
    tokens = shlex.split(raw, posix=True)
    result: list[str] = []
    index = 0
    while index < len(tokens):
        option = tokens[index]
        if option in FLAG_OPTIONS:
            result.append(option)
            index += 1
            continue
        if option in VALUE_OPTIONS:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                raise ValueError(f"{option} requires a value")
            value = tokens[index + 1]
            try:
                parsed = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError(f"{option} requires a numeric value") from exc
            if not parsed.is_finite() or parsed < 0:
                raise ValueError(f"{option} requires a finite non-negative value")
            result.extend((option, value))
            index += 2
            continue
        raise ValueError(f"service argument is not allowlisted: {option}")
    return result


def main() -> int:
    try:
        args = parse_extra_args(sys.argv[1] if len(sys.argv) > 1 else "")
    except ValueError as exc:
        print(f"[SECURITY] {exc}", file=sys.stderr)
        return 2
    for value in args:
        sys.stdout.buffer.write(value.encode("utf-8") + b"\0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
