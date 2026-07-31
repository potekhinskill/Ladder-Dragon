# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
"""Tests for the project technical-English documentation check."""

from pathlib import Path

from ladder_dragon.verification.technical_english import check_document, check_documents


def test_technical_english_check_accepts_short_prose_and_ignores_code(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text(
        "# Guide\n\n"
        "Use one term for one meaning.\n\n"
        "1. Stop the service.\n\n"
        "```bash\n"
        "echo \"this command can contain text that is not technical prose\"\n"
        "```\n",
        encoding="utf-8",
    )

    assert check_document(path) == []


def test_technical_english_check_rejects_long_instruction_and_contraction(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text(
        "# Guide\n\n"
        "1. Don't start this service until the operator verifies every exchange order, every journal row, every balance, every fill, every identifier, and every protection leg.\n",
        encoding="utf-8",
    )

    rules = {issue.rule for issue in check_document(path)}
    assert rules == {"STE-CONTRACTION", "STE-SENTENCE-LENGTH"}


def test_technical_english_check_counts_wrapped_list_continuations(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text(
        "# Guide\n\n"
        "1. Stop the service after the operator verifies each exchange order,\n"
        "   journal row, account balance, fill, identifier, protection leg, and database record.\n",
        encoding="utf-8",
    )

    assert [issue.rule for issue in check_document(path)] == ["STE-SENTENCE-LENGTH"]


def test_all_current_project_guides_match_technical_english_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    assert check_documents(root) == []
