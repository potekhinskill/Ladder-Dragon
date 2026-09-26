# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: select the project interpreter before verification imports.
'Dependency-free verification interpreter bootstrap.'

from __future__ import annotations

import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_VENV_REEXEC_MARKER = "LADDER_DRAGON_HARNESS_VENV_REEXEC"


def _project_venv_python(project_root: Path) -> Path:
    """Return the canonical project interpreter path for this platform."""
    if os.name == "nt":
        return project_root / ".venv" / "Scripts" / "python.exe"
    return project_root / ".venv" / "bin" / "python"


def _reexec_project_venv_if_needed(
    *,
    project_root: Path = PROJECT_ROOT,
    prefix: str | Path | None = None,
    environ: dict[str, str] | None = None,
    execve_fn=None,
) -> bool:
    """Re-execute the CLI in the repository venv before verification imports.

    CI images without a repository-local venv continue with their explicitly
    provisioned interpreter. A local checkout that has ``.venv`` always uses
    it, so a host Python cannot fail halfway through dependency imports.
    """
    candidate = _project_venv_python(project_root)
    if not candidate.is_file():
        return False
    active_prefix = Path(prefix or sys.prefix).resolve()
    expected_prefix = candidate.parent.parent.resolve()
    if active_prefix == expected_prefix:
        return False
    environment = dict(os.environ if environ is None else environ)
    if environment.get(_VENV_REEXEC_MARKER) == "1":
        raise SystemExit(
            "verification harness could not enter the project virtual environment"
        )
    environment[_VENV_REEXEC_MARKER] = "1"
    command = [
        str(candidate),
        "-m",
        "bin.verification_harness",
        *sys.argv[1:],
    ]
    execute = execve_fn or os.execve
    try:
        execute(str(candidate), command, environment)
    except OSError as exc:
        raise SystemExit(
            f"verification harness cannot execute {candidate}"
        ) from exc
    return True
