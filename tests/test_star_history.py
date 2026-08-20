# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify accurate and privacy-safe Star History generation.
"""Tests for the repository-owned Star History generator."""

from __future__ import annotations

from datetime import date
from io import BytesIO
import json
from urllib.error import HTTPError

import pytest

from bin import generate_star_history
from bin.generate_star_history import (
    StarHistoryError,
    fetch_repository_snapshot,
    main,
    merge_snapshot,
    render_svg,
)


REPOSITORY = "potekhinskill/Ladder-Dragon"


def _history() -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "created_at": "2026-07-18T09:39:54Z",
        "samples": [
            {"date": "2026-07-18", "count": 0},
            {"date": "2026-07-20", "count": 1},
            {
                "date": "2026-07-25",
                "count": 2,
                "user": {"login": "must-not-leak"},
            },
        ],
    }


def _snapshot(count: int = 2) -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "created_at": "2026-07-18T09:39:54Z",
        "stargazers_count": count,
    }


def _write_seed(path) -> None:
    path.write_text(json.dumps(_history()), encoding="utf-8")


def test_star_history_svg_uses_only_aggregate_snapshots():
    svg = render_svg(_history(), date(2026, 7, 26))
    assert "2 ★" in svg
    assert "Current count: 2." in svg
    assert "2026-07-18" in svg
    assert "2026-07-26" in svg
    assert "must-not-leak" not in svg
    assert "Official GitHub metadata" in svg
    assert "event update + daily reconciliation" in svg


def test_star_history_fetches_only_repository_metadata(monkeypatch):
    observed: dict[str, str] = {}

    def fake_request(url, token=""):
        observed.update(url=url, token=token)
        return {
            "created_at": "2026-07-18T09:39:54Z",
            "stargazers_count": 2,
            "owner": {"login": "must-not-persist"},
        }

    monkeypatch.setattr(generate_star_history, "_request_json", fake_request)
    snapshot = fetch_repository_snapshot(REPOSITORY, "workflow-token")
    assert observed == {
        "url": f"https://api.github.com/repos/{REPOSITORY}",
        "token": "workflow-token",
    }
    assert snapshot == _snapshot()
    assert "owner" not in snapshot


def test_star_history_merges_daily_counts_and_allows_removals():
    state = merge_snapshot(_history(), _snapshot(1), date(2026, 7, 26))
    assert state["samples"][-1] == {"date": "2026-07-26", "count": 1}
    replaced = merge_snapshot(state, _snapshot(2), date(2026, 7, 26))
    assert len(replaced["samples"]) == len(state["samples"])
    assert replaced["samples"][-1] == {
        "date": "2026-07-26",
        "count": 2,
    }


def test_star_history_rejects_damaged_or_overlapping_state():
    damaged = _history()
    damaged["samples"] = [
        {"date": "2026-07-20", "count": 1},
        {"date": "2026-07-20", "count": 2},
    ]
    with pytest.raises(StarHistoryError, match="history_sample_invalid"):
        merge_snapshot(damaged, _snapshot(), date(2026, 7, 26))


def test_star_history_response_reader_has_a_byte_ceiling(monkeypatch):
    monkeypatch.setattr(generate_star_history, "MAX_RESPONSE_BYTES", 8)
    with pytest.raises(StarHistoryError, match="response_too_large"):
        generate_star_history._read_json_stream(BytesIO(b'{"count":12}'))


def test_star_history_cli_fails_closed_on_malformed_input(tmp_path):
    source = tmp_path / "snapshot.json"
    seed = tmp_path / "seed.json"
    output = tmp_path / "star-history.svg"
    state_output = tmp_path / "star-history.json"
    source.write_text(json.dumps({"stargazers_count": "invalid"}), encoding="utf-8")
    _write_seed(seed)
    result = main(
        [
            "--repository",
            REPOSITORY,
            "--input-json",
            str(source),
            "--seed-json",
            str(seed),
            "--state-output",
            str(state_output),
            "--output",
            str(output),
        ]
    )
    assert result == 1
    assert not output.exists()
    assert not state_output.exists()


def test_star_history_cli_writes_svg_and_bounded_state(tmp_path):
    source = tmp_path / "snapshot.json"
    seed = tmp_path / "seed.json"
    output = tmp_path / "star-history.svg"
    state_output = tmp_path / "star-history.json"
    source.write_text(json.dumps(_snapshot()), encoding="utf-8")
    _write_seed(seed)
    result = main(
        [
            "--repository",
            REPOSITORY,
            "--input-json",
            str(source),
            "--seed-json",
            str(seed),
            "--state-output",
            str(state_output),
            "--output",
            str(output),
        ]
    )
    assert result == 0
    assert "2 ★" in output.read_text(encoding="utf-8")
    state = json.loads(state_output.read_text(encoding="utf-8"))
    assert state["repository"] == REPOSITORY
    assert len(state["samples"]) <= generate_star_history.MAX_HISTORY_SAMPLES


def test_star_history_cli_never_prints_provider_url_or_token(
    monkeypatch,
    tmp_path,
    capsys,
):
    seed = tmp_path / "seed.json"
    _write_seed(seed)
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-token")

    def fail_fetch(repository, token):
        raise HTTPError(
            f"https://api.github.com/repos/{repository}?token={token}",
            403,
            "forbidden secret-response",
            {},
            None,
        )

    monkeypatch.setattr(
        generate_star_history,
        "fetch_repository_snapshot",
        fail_fetch,
    )
    result = main(
        [
            "--repository",
            REPOSITORY,
            "--seed-json",
            str(seed),
            "--state-output",
            str(tmp_path / "state.json"),
            "--output",
            str(tmp_path / "history.svg"),
        ]
    )
    captured = capsys.readouterr().out
    assert result == 1
    assert "status=403" in captured
    assert "token=" not in captured
    assert "workflow-token" not in captured
    assert "secret-response" not in captured
