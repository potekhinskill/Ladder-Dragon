# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
"""Contracts between current documentation and executable interfaces."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_readme_uses_current_backtest_cli() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "-m bin.backtest data.csv --output report.json" in readme
    assert "--archive archive.jsonl" in readme
    assert "--events-jsonl" not in readme
    assert "-m bin.backtest --csv" not in readme


def test_command_reference_lists_all_cli_modules() -> None:
    reference = (ROOT / "docs" / "COMMAND_REFERENCE.md").read_text(encoding="utf-8")
    module_names = {
        path.stem for path in (ROOT / "bin").glob("*.py") if path.name != "__init__.py"
    }

    missing = sorted(name for name in module_names if f"`{name}`" not in reference)
    assert missing == []


def test_command_reference_lists_all_systemd_units() -> None:
    reference = (ROOT / "docs" / "COMMAND_REFERENCE.md").read_text(encoding="utf-8")
    units = list((ROOT / "deploy").glob("*.service"))
    units.extend((ROOT / "deploy").glob("*.timer"))

    missing = sorted(path.name for path in units if path.name not in reference)
    assert missing == []


def test_guides_do_not_name_unknown_project_units() -> None:
    known = {path.name for path in (ROOT / "deploy").glob("*.service")}
    known.update(path.name for path in (ROOT / "deploy").glob("*.timer"))
    unit_pattern = re.compile(
        r"(?:ladder-dragon-[a-z0-9-]+|mybot|pi-dashboard|pi-watchdog-v3)"
        r"\.(?:service|timer)"
    )
    guides = [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]

    referenced = {
        match.group(0)
        for path in guides
        for match in unit_pattern.finditer(path.read_text(encoding="utf-8"))
    }
    assert sorted(referenced - known) == []


def test_readme_links_current_reference_documents() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for name in ("IMPLEMENTATION_STATUS.md", "CONFIGURATION.md", "COMMAND_REFERENCE.md"):
        assert name in readme
