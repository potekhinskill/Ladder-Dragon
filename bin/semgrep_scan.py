# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run the pinned isolated Semgrep policy without network access.

from ladder_dragon.verification.semgrep_command import main

if __name__ == "__main__":
    raise SystemExit(main())
