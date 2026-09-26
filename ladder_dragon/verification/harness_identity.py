# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve the checked-out verification source identity.
'Verification checkout identity.'

from __future__ import annotations

import re
import subprocess

from ladder_dragon.harness_bootstrap import PROJECT_ROOT


def _commit_sha() -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return "0" * 40
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else "0" * 40
