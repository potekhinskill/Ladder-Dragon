# Third-party notices

The MIT license in `LICENSE` applies to Ladder Dragon source code only. Runtime
dependencies and bundled assets keep their own licenses. Versions are pinned in
`pyproject.toml` or in the dashboard source.

## Python dependencies

- `python-dotenv` — BSD 3-Clause License.
- `requests` — Apache License 2.0.
- `fastapi` — MIT License.
- `psutil` — BSD 3-Clause License.
- `uvicorn` — BSD 3-Clause License.
- `httpx` — BSD 3-Clause License.
- `pytest` — MIT License (test dependency only).

## Bundled dashboard asset

- `FRONT/vendor/chart.umd.min.js` — Chart.js 4.4.3, MIT License. The file
  retains the upstream license header.

No production account data, credentials, or private configuration is included
in this notice. Dependency versions and known vulnerabilities are checked in CI
with `pip-audit`; update this file when direct dependencies change.
