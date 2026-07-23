#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: manage the explicit Raspberry Pi trading maintenance marker.
"""Set, clear or inspect the sanitized trading maintenance state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ladder_dragon.execution.maintenance_state import (
    DEFAULT_PATH,
    clear_maintenance,
    load_maintenance_state,
    set_maintenance,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("set", "clear", "status"))
    parser.add_argument("--reason", default="Operator intentionally stopped trading")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(os.getenv("BOT_MAINTENANCE_FILE", str(DEFAULT_PATH))),
    )
    args = parser.parse_args(argv)
    if args.command == "set":
        state = set_maintenance(args.path, args.reason)
    elif args.command == "clear":
        state = clear_maintenance(args.path)
    else:
        state = load_maintenance_state(args.path)
    print(json.dumps({
        "active": state.active,
        "reason": state.reason,
        "updated_at_epoch": state.updated_at_epoch,
    }, sort_keys=True))
    return 2 if state.active else 0


if __name__ == "__main__":
    raise SystemExit(main())
