# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the executable command interface.
from ladder_dragon.execution.ip_guard_command import cli as main

if __name__ == "__main__":
    raise SystemExit(main())
