# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose offline history-launch preparation without collection authority.
from ladder_dragon.strategy.history_launcher import main

if __name__ == '__main__':
    raise SystemExit(main())
