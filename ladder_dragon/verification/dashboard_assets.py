# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify that published dashboard assets exactly match the release.
"""Fail closed when the Raspberry Pi dashboard publication is incomplete."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DASHBOARD_ASSETS: tuple[tuple[str, str], ...] = (
    ("FRONT/index.html", "index.html"),
    ("FRONT/help.html", "help.html"),
    ("FRONT/dashboard.css", "dashboard.css"),
    ("FRONT/dashboard.js", "dashboard.js"),
    ("FRONT/help.css", "help.css"),
    ("FRONT/readme.css", "readme.css"),
    ("FRONT/locales.js", "locales.js"),
    ("FRONT/vendor/chart.umd.min.js", "vendor/chart.umd.min.js"),
    (
        "FRONT/vendor/chart.js.LICENSE.txt",
        "vendor/chart.js.LICENSE.txt",
    ),
    ("docs/assets/ladder-dragon-logo.svg", "ladder-dragon-logo.svg"),
    (
        "docs/assets/ladder-dragon-dashboard-icon.svg",
        "ladder-dragon-dashboard-icon.svg",
    ),
    ("CHANGELOG.md", "CHANGELOG.md"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dashboard_asset_failures(
    source_root: Path,
    web_root: Path,
) -> tuple[str, ...]:
    """Return non-secret asset names that are missing or differ."""
    failures: list[str] = []
    for source_name, published_name in DASHBOARD_ASSETS:
        source = source_root / source_name
        published = web_root / published_name
        if not source.is_file():
            failures.append(f"source_missing:{source_name}")
        elif not published.is_file():
            failures.append(f"published_missing:{published_name}")
        elif _sha256(source) != _sha256(published):
            failures.append(f"content_mismatch:{published_name}")
    return tuple(failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--web-root", required=True, type=Path)
    args = parser.parse_args(argv)
    failures = dashboard_asset_failures(args.source_root, args.web_root)
    payload = {
        "assets_checked": len(DASHBOARD_ASSETS),
        "failures": list(failures),
        "status": "PASS" if not failures else "FAILED",
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
