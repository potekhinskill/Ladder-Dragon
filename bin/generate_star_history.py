#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: generate a privacy-safe repository star-count chart from GitHub data.
"""Generate a Star History SVG from bounded aggregate GitHub snapshots."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
API_ROOT = "https://api.github.com"
MAX_RESPONSE_BYTES = 128 * 1024
MAX_HISTORY_SAMPLES = 3_660


class StarHistoryError(ValueError):
    """Describe one safe validation failure without provider response data."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _read_json_stream(stream: BinaryIO) -> object:
    body = bytearray()
    while True:
        chunk = stream.read(8_192)
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise StarHistoryError("response_too_large")
    try:
        return json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarHistoryError("response_json_invalid") from exc


def _request_json(url: str, token: str = "") -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Ladder-Dragon-Star-History",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return _read_json_stream(response)


def fetch_repository_snapshot(
    repository: str,
    token: str,
) -> dict[str, object]:
    """Read only aggregate repository metadata from the official REST API."""
    if not REPOSITORY_RE.fullmatch(repository):
        raise StarHistoryError("repository_invalid")
    payload = _request_json(f"{API_ROOT}/repos/{repository}", token)
    if not isinstance(payload, dict):
        raise StarHistoryError("repository_metadata_invalid")
    created_at = payload.get("created_at")
    count = payload.get("stargazers_count")
    if not isinstance(created_at, str):
        raise StarHistoryError("repository_created_at_invalid")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise StarHistoryError("repository_star_count_invalid")
    return {
        "repository": repository,
        "created_at": created_at,
        "stargazers_count": count,
    }


def _parse_date(value: object) -> date:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise StarHistoryError("date_invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def _validate_state(
    payload: object,
    *,
    repository: str,
) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise StarHistoryError("history_schema_invalid")
    if payload.get("repository") != repository:
        raise StarHistoryError("history_repository_differs")
    created_at = payload.get("created_at")
    created_on = _parse_date(created_at)
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise StarHistoryError("history_samples_invalid")
    if len(raw_samples) > MAX_HISTORY_SAMPLES:
        raise StarHistoryError("history_capacity_reached")
    samples: list[dict[str, object]] = []
    previous: date | None = None
    for raw in raw_samples:
        if not isinstance(raw, dict):
            raise StarHistoryError("history_sample_invalid")
        sample_on = _parse_date(raw.get("date"))
        count = raw.get("count")
        if (
            sample_on < created_on
            or (previous is not None and sample_on <= previous)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise StarHistoryError("history_sample_invalid")
        samples.append({"date": sample_on.isoformat(), "count": count})
        previous = sample_on
    return {
        "schema_version": 1,
        "repository": repository,
        "created_at": str(created_at),
        "samples": samples,
    }


def _load_json_file(path: Path) -> object:
    if path.stat().st_size > MAX_RESPONSE_BYTES:
        raise StarHistoryError("input_too_large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarHistoryError("input_json_invalid") from exc


def _load_previous_state(
    url: str,
    *,
    repository: str,
) -> dict[str, object] | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise StarHistoryError("history_url_invalid")
    try:
        payload = _request_json(url)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return _validate_state(payload, repository=repository)


def merge_snapshot(
    state: dict[str, object],
    snapshot: dict[str, object],
    generated_on: date,
) -> dict[str, object]:
    repository = str(snapshot.get("repository") or "")
    validated = _validate_state(state, repository=repository)
    if _parse_date(validated["created_at"]) != _parse_date(
        snapshot.get("created_at")
    ):
        raise StarHistoryError("repository_creation_date_differs")
    current_count = snapshot.get("stargazers_count")
    if (
        isinstance(current_count, bool)
        or not isinstance(current_count, int)
        or current_count < 0
    ):
        raise StarHistoryError("repository_star_count_invalid")
    raw_samples = validated["samples"]
    if not isinstance(raw_samples, list):
        raise StarHistoryError("history_samples_invalid")
    samples = [dict(item) for item in raw_samples]
    latest_on = _parse_date(samples[-1]["date"])
    if generated_on < latest_on:
        raise StarHistoryError("generation_date_precedes_history")
    current = {"date": generated_on.isoformat(), "count": current_count}
    if generated_on == latest_on:
        samples[-1] = current
    else:
        if len(samples) >= MAX_HISTORY_SAMPLES:
            raise StarHistoryError("history_capacity_reached")
        samples.append(current)
    return {**validated, "samples": samples}


def render_svg(payload: dict[str, object], generated_on: date) -> str:
    repository = str(payload.get("repository") or "")
    state = _validate_state(payload, repository=repository)
    created_on = _parse_date(state["created_at"])
    if generated_on < created_on:
        raise StarHistoryError("generation_date_precedes_repository")
    raw_samples = state["samples"]
    if not isinstance(raw_samples, list):
        raise StarHistoryError("history_samples_invalid")
    observations = [
        (_parse_date(item["date"]), int(item["count"]))
        for item in raw_samples
    ]
    if observations[-1][0] > generated_on:
        raise StarHistoryError("generation_date_precedes_history")

    days = max(1, (generated_on - created_on).days)
    sample_count = min(120, days + 1)
    current_count = observations[0][1]
    observation_index = 0
    points: list[tuple[float, int]] = []
    for index in range(sample_count):
        offset = round(days * index / max(1, sample_count - 1))
        sample_on = date.fromordinal(created_on.toordinal() + offset)
        while (
            observation_index + 1 < len(observations)
            and observations[observation_index + 1][0] <= sample_on
        ):
            observation_index += 1
            current_count = observations[observation_index][1]
        x = 76 + (816 * index / max(1, sample_count - 1))
        points.append((x, current_count))
    total = observations[-1][1]
    maximum = max(1, *(count for _, count in observations))
    coordinates = [
        f"{x:.1f},{230 - (118 * count / maximum):.1f}"
        for x, count in points
    ]
    if len(coordinates) == 1:
        coordinates.insert(0, "76.0,230.0")
    path = "M" + " L".join(coordinates)
    end_y = 230 - (118 * total / maximum)
    safe_repository = escape(repository)
    description = escape(
        f"GitHub star-count snapshots from {created_on.isoformat()} through "
        f"{generated_on.isoformat()}. Current count: {total}."
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="300" viewBox="0 0 960 300" role="img" aria-labelledby="title description">
  <title id="title">{safe_repository} GitHub star history</title>
  <desc id="description">{description}</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#111827"/><stop offset="1" stop-color="#0b1220"/></linearGradient>
    <linearGradient id="line" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#5b8cff"/><stop offset="1" stop-color="#21c07a"/></linearGradient>
  </defs>
  <rect width="960" height="300" rx="18" fill="url(#background)"/>
  <rect x="0.5" y="0.5" width="959" height="299" rx="17.5" fill="none" stroke="#29344a"/>
  <text x="44" y="50" fill="#f8fafc" font-family="system-ui,sans-serif" font-size="22" font-weight="700">GitHub Star History</text>
  <text x="44" y="76" fill="#94a3b8" font-family="system-ui,sans-serif" font-size="14">{safe_repository}</text>
  <text x="892" y="55" text-anchor="end" fill="#f8fafc" font-family="system-ui,sans-serif" font-size="30" font-weight="800">{total} ★</text>
  <text x="892" y="76" text-anchor="end" fill="#94a3b8" font-family="system-ui,sans-serif" font-size="12">current stars</text>
  <line x1="76" y1="112" x2="76" y2="230" stroke="#334155"/>
  <line x1="76" y1="230" x2="892" y2="230" stroke="#334155"/>
  <line x1="76" y1="112" x2="892" y2="112" stroke="#1e293b" stroke-dasharray="5 7"/>
  <text x="62" y="116" text-anchor="end" fill="#64748b" font-family="system-ui,sans-serif" font-size="12">{maximum}</text>
  <text x="62" y="234" text-anchor="end" fill="#64748b" font-family="system-ui,sans-serif" font-size="12">0</text>
  <text x="76" y="256" fill="#64748b" font-family="system-ui,sans-serif" font-size="12">{created_on.isoformat()}</text>
  <text x="892" y="256" text-anchor="end" fill="#64748b" font-family="system-ui,sans-serif" font-size="12">{generated_on.isoformat()}</text>
  <path d="{path}" fill="none" stroke="url(#line)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="892" cy="{end_y:.1f}" r="7" fill="#21c07a" stroke="#d1fae5" stroke-width="2"/>
  <text x="484" y="278" text-anchor="middle" fill="#64748b" font-family="system-ui,sans-serif" font-size="12">Official GitHub metadata · event update + daily reconciliation</text>
</svg>
"""


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state-output", required=True, type=Path)
    parser.add_argument("--seed-json", required=True, type=Path)
    parser.add_argument("--previous-url", default="")
    parser.add_argument("--input-json", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output.resolve() == args.state_output.resolve():
            raise StarHistoryError("output_paths_conflict")
        snapshot = (
            _load_json_file(args.input_json)
            if args.input_json
            else fetch_repository_snapshot(
                args.repository,
                os.getenv("GITHUB_TOKEN", ""),
            )
        )
        if not isinstance(snapshot, dict):
            raise StarHistoryError("repository_metadata_invalid")
        snapshot["repository"] = args.repository
        previous = _load_previous_state(
            args.previous_url,
            repository=args.repository,
        )
        seed = _validate_state(
            _load_json_file(args.seed_json),
            repository=args.repository,
        )
        state = previous or seed
        generated_on = datetime.now(timezone.utc).date()
        merged = merge_snapshot(state, snapshot, generated_on)
        svg = render_svg(merged, generated_on)
        state_json = json.dumps(
            merged,
            indent=2,
            sort_keys=True,
        ) + "\n"
        _write_text(args.state_output, state_json)
        _write_text(args.output, svg)
    except HTTPError as exc:
        print(
            "star history generation failed: "
            f"error_type=HTTPError status={exc.code}"
        )
        return 1
    except (
        URLError,
        OSError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
    ) as exc:
        code = exc.code if isinstance(exc, StarHistoryError) else "unavailable"
        print(
            "star history generation failed: "
            f"error_type={type(exc).__name__} code={code}"
        )
        return 1
    print(f"wrote {args.output} and {args.state_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
