# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify accurate and privacy-safe Star History generation.
"""Tests for the repository-owned Star History generator."""

from __future__ import annotations

from datetime import date
import json

from bin.generate_star_history import main, render_svg


def _history() -> dict[str, object]:
    return {
        "repository": "potekhinskill/Ladder-Dragon",
        "created_at": "2026-07-18T08:00:00Z",
        "stargazers": [
            {
                "starred_at": "2026-07-20T12:00:00Z",
                "user": {"login": "must-not-leak"},
            },
            {
                "starred_at": "2026-07-25T13:00:00Z",
                "user": {"login": "also-private"},
            },
        ],
    }


def test_star_history_svg_counts_stars_without_publishing_accounts():
    svg = render_svg(_history(), date(2026, 7, 26))
    assert "2 ★" in svg
    assert "Current count: 2." in svg
    assert "2026-07-18" in svg
    assert "2026-07-26" in svg
    assert "must-not-leak" not in svg
    assert "also-private" not in svg
    assert "Official GitHub Stargazers API" in svg


def test_star_history_cli_fails_closed_on_malformed_input(tmp_path):
    source = tmp_path / "history.json"
    output = tmp_path / "star-history.svg"
    source.write_text(json.dumps({"stargazers": "invalid"}), encoding="utf-8")
    result = main(
        [
            "--repository",
            "potekhinskill/Ladder-Dragon",
            "--input-json",
            str(source),
            "--output",
            str(output),
        ]
    )
    assert result == 1
    assert not output.exists()
