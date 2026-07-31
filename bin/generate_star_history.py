#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: generate a privacy-safe repository star chart from GitHub data.
"""Generate a Star History SVG from the official GitHub Stargazers API."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GRAPHQL_URL = "https://api.github.com/graphql"
STARGAZERS_QUERY = """
query StarHistory(
  $owner: String!
  $name: String!
  $cursor: String
) {
  repository(owner: $owner, name: $name) {
    createdAt
    stargazerCount
    stargazers(
      first: 100
      after: $cursor
      orderBy: {field: STARRED_AT, direction: ASC}
    ) {
      edges { starredAt }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def _graphql_json(
    query: str,
    variables: dict[str, object],
    token: str,
) -> dict[str, object]:
    if not token:
        raise ValueError("GitHub token is required for GraphQL")
    headers = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "Ladder-Dragon-Star-History",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }
    body = json.dumps(
        {"query": query, "variables": variables},
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(GRAPHQL_URL, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("GitHub GraphQL response contains errors")
    return payload


def fetch_history(repository: str, token: str) -> dict[str, object]:
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use the owner/name format")
    owner, name = repository.split("/", 1)
    stargazers: list[dict[str, str]] = []
    cursor: str | None = None
    created_at: str | None = None
    expected_count: int | None = None
    while True:
        payload = _graphql_json(
            STARGAZERS_QUERY,
            {"owner": owner, "name": name, "cursor": cursor},
            token,
        )
        data = payload.get("data")
        repo = data.get("repository") if isinstance(data, dict) else None
        if not isinstance(repo, dict) or not isinstance(
            repo.get("createdAt"), str
        ):
            raise ValueError("GitHub repository metadata is invalid")
        created_at = repo["createdAt"]
        expected_count = int(repo.get("stargazerCount", -1))
        connection = repo.get("stargazers")
        if not isinstance(connection, dict):
            raise ValueError("GitHub stargazer connection is invalid")
        edges = connection.get("edges")
        page_info = connection.get("pageInfo")
        if not isinstance(edges, list) or not isinstance(page_info, dict):
            raise ValueError("GitHub stargazer page is invalid")
        for edge in edges:
            starred_at = edge.get("starredAt") if isinstance(edge, dict) else None
            if not isinstance(starred_at, str):
                raise ValueError("GitHub stargazer timestamp is invalid")
            stargazers.append({"starred_at": starred_at})
        if page_info.get("hasNextPage") is not True:
            break
        cursor = page_info.get("endCursor")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("GitHub stargazer cursor is invalid")
    if expected_count != len(stargazers):
        raise ValueError("GitHub stargazer count differs from history")
    return {
        "repository": repository,
        "created_at": created_at,
        "stargazers": stargazers,
    }


def _parse_date(value: object) -> date:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def render_svg(payload: dict[str, object], generated_on: date) -> str:
    repository = str(payload.get("repository") or "")
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("history repository is invalid")
    created_on = _parse_date(payload.get("created_at"))
    if generated_on < created_on:
        raise ValueError("generation date precedes repository creation")
    raw_stargazers = payload.get("stargazers")
    if not isinstance(raw_stargazers, list):
        raise ValueError("stargazers must be a list")
    stars_by_day: Counter[date] = Counter()
    for item in raw_stargazers:
        if not isinstance(item, dict) or "starred_at" not in item:
            raise ValueError("stargazer record is invalid")
        starred_on = _parse_date(item["starred_at"])
        if created_on <= starred_on <= generated_on:
            stars_by_day[starred_on] += 1

    days = max(1, (generated_on - created_on).days)
    samples = min(120, days + 1)
    cumulative = 0
    events = sorted(stars_by_day.items())
    points: list[tuple[float, int]] = []
    event_index = 0
    for index in range(samples):
        offset = round(days * index / max(1, samples - 1))
        sample_date = date.fromordinal(created_on.toordinal() + offset)
        while event_index < len(events) and events[event_index][0] <= sample_date:
            cumulative += events[event_index][1]
            event_index += 1
        x = 76 + (816 * index / max(1, samples - 1))
        points.append((x, cumulative))
    if events and event_index < len(events):
        cumulative += sum(count for _, count in events[event_index:])
    total = sum(stars_by_day.values())
    maximum = max(1, total)
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
        f"GitHub stars from {created_on.isoformat()} through "
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
  <text x="484" y="278" text-anchor="middle" fill="#64748b" font-family="system-ui,sans-serif" font-size="12">Official GitHub Stargazers API · event update + hourly reconciliation</text>
</svg>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input-json", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input_json:
            payload = json.loads(args.input_json.read_text(encoding="utf-8"))
        else:
            payload = fetch_history(
                args.repository,
                os.getenv("GITHUB_TOKEN", ""),
            )
        if not isinstance(payload, dict):
            raise ValueError("history payload is not an object")
        payload["repository"] = args.repository
        svg = render_svg(payload, datetime.now(timezone.utc).date())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(svg, encoding="utf-8")
    except (
        HTTPError,
        URLError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"star history generation failed: {type(exc).__name__}")
        return 1
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
