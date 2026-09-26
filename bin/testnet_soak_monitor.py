# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a Testnet soak boundary without changing monitoring behavior.
from ladder_dragon.verification.live.soak_command import main

if __name__ == "__main__":
    raise SystemExit(main())
