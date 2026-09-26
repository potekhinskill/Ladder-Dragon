#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: select the project interpreter before importing verification dependencies.
from ladder_dragon.harness_bootstrap import _reexec_project_venv_if_needed

if __name__ == "__main__":
    _reexec_project_venv_if_needed()

from ladder_dragon.verification.harness_command import main

if __name__ == "__main__":
    raise SystemExit(main())
