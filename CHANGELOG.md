# Changelog — Ladder Dragon

All notable changes are documented here. Releases use Semantic Versioning; every
section is dated and there is intentionally no `Unreleased` section.

## [2.10.51] — 2026-07-19

### Added
- Added a read-only dashboard GitHub update indicator for the configured repository
  and branch.
- The backend checks GitHub at most once per hour (configurable with
  DASHBOARD_GITHUB_UPDATE_CHECK_SEC), caches the result, and never pulls or
  deploys automatically.
- Added optional backend-only DASHBOARD_GITHUB_TOKEN support for private
  repositories without exposing the token to the browser.

### Verified
- PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q — all tests pass.
- Dashboard security tests and Python compilation pass.
- git diff --check passes.

## [2.10.50] — 2026-07-18

### Security
- Removed the obsolete `docs/legacy-systemd-notes.txt` from the public tree.
- Added ignore rules for `key_start_bot.txt` so copied credential notes cannot be
  reintroduced accidentally.
- Prepared the repository history for removal of the historical `key_start_bot.txt`
  path; existing public GitHub commits must be replaced with the rewritten history.

### Verified
- Confirmed that no current worktree path named `key_start_bot.txt` exists.
- Secret scans report no technical key material in the remaining tracked files.

## [2.10.49] — 2026-07-18

### Changed
- Translated project documentation, runbooks, policy files, and public release
  notes to English while keeping the dashboard locale catalog intact.
- Preserved runtime behavior, API contracts, identifiers, and exchange payloads.

### Verified
- Full Python test suite, compile check, JavaScript syntax check, shell syntax
  check, and `git diff --check` pass.

## [2.10.48] — 2026-07-18

### Changed
- Added the public project contact `potekhin.skill@gmail.com` to README and
  copyright documentation only; the address is not placed in runtime secrets.

## [2.10.47] — 2026-07-18

### Changed
- Replaced the shared `docs/assets/ladder-dragon-logo.svg` with the supplied
  icon asset and updated dashboard, README, and deployment copies.

## [2.10.46] — 2026-07-18

### Changed
- Replaced repetitive maintenance headers with short, file-specific comments.
- Trading behavior, data formats, and public APIs were unchanged.

## [2.10.45] — 2026-07-18

### Changed
- Added the Ladder Dragon logo to the dashboard.
- Added cross-platform host telemetry for Linux, macOS, Windows/WSL, and Raspberry;
  Raspberry-only voltage and throttling fields now report when unsupported.
- Installer and updater publish the logo with read-only dashboard assets.

## [2.10.44] — 2026-07-18

### Added
- Added a dashboard locale catalog with English, Russian, Chinese, Spanish,
  German, French, Italian, Kazakh, Ukrainian, Korean, Japanese, Portuguese,
  Estonian, Finnish, and Danish.
- Added a persistent language selector with English fallback.

## [2.10.43] — 2026-07-18

### Changed
- Standardized production comments and dashboard maintenance notes in English.
- Documented the copyright and public-contact policy.

## [2.10.42] — 2026-07-18

### Added
- Added the SVG logo and cross-platform introduction for Raspberry, Linux,
  macOS, and Windows through WSL2.

## [2.10.41] — 2026-07-18

### Added
- Added MIT licensing and a financial-risk disclaimer.
- Documented the project owner without publishing private identity data.

## [2.10.40] — 2026-07-18

### Fixed
- Dashboard no longer calls an entirely unfilled order a partial fill.

## [2.10.39] — 2026-07-18

### Fixed
- Separated Binance diagnostics from generic network status.
- Displayed USB read/write state and abnormal clock/latency warnings.
- Preserved published CAP, reserve, and reconciliation fields in AI heartbeat snapshots.

## [2.10.38] — 2026-07-18

### Added
- Added Raspberry/backup, LIVE/Risk, FIFO position, OCO/STOP, and AI data-quality
  blocks to the read-only dashboard.
- Added safe backup status metadata and host health telemetry.

## [2.10.37] — 2026-07-18

### Changed
- Renamed the dashboard title and main screen to Ladder Dragon.

## [2.10.36] — 2026-07-18

### Changed
- Made the AI card compact with two columns and responsive one-column fallback.

## [2.10.35] — 2026-07-18

### Fixed
- Fixed the dashboard launcher after moving CLI entry points into `bin/`.

## [2.10.34] — 2026-07-18

### Changed
- Completed the responsibility-based package layout and Raspberry updater paths.

## [2.10.33] — 2026-07-18

### Fixed
- Added startup checks for account/ledger reconciliation and explicit unvalued-asset acknowledgement.

## [2.10.32] — 2026-07-18

### Added
- Added per-symbol balances, open orders, order status, and last-fill telemetry to the dashboard.

## [2.10.31] — 2026-07-18

### Fixed
- Added exact exchange trade/order to FIFO lot mapping and prevented unresolved fills from entering PnL.

## [2.10.30] — 2026-07-18

### Added
- Added Testnet BUY → fill → OCO → restart recovery smoke coverage and isolated circuit drills.

## [2.10.29] — 2026-07-18

### Fixed
- Added fail-closed handling for lost Binance acknowledgements, gap-below-stop, and partial protection.

## [2.10.28] — 2026-07-18

### Added
- Added AI decision attribution, RAG retrieval journaling, virtual-shadow evaluation, and production gates.

## [2.10.27] — 2026-07-18

### Changed
- Added cost, token, request, and stale-context budgets with deterministic fallback.

## [2.10.26] — 2026-07-18

### Fixed
- Hardened backup SQLite online-copy handling, atomic archive publication, and WAL/SHM recovery.

## [2.10.25] — 2026-07-18

### Changed
- Added account balance valuation, visible reserve state, and conservative handling of unvalued dust assets.

## [2.10.24] — 2026-07-18

### Added
- Added encrypted rotating backups, external-disk mirroring, protected `/backups/`, and Telegram outbox retry.

## [2.10.23] — 2026-07-18

### Fixed
- Fixed watchdog duplicate suppression, network-loss alerts, Binance authentication alerts, and temperature/load reporting.

## [2.10.22] — 2026-07-18

### Added
- Added Raspberry Pi installer, updater, systemd units, nginx protection, and sanitized operational log export.

## [2.10.21] — 2026-07-18

### Changed
- Centralized execution configuration and preserved venue/mode/symbol choices across updates.

## [2.10.20] — 2026-07-18

### Fixed
- Improved fill synchronization, commission accounting, ledger reconciliation, and restart-safe order journals.

## [2.10.19] — 2026-07-18

### Added
- Added FIFO lots, time-stop metadata, OCO lot identifiers, and partial-fill accounting.

## [2.10.18] — 2026-07-18

### Changed
- Added exact client-order decision mapping and separate real/virtual RAG statistics.

## [2.10.17] — 2026-07-18

### Fixed
- Added AI rationale length validation, schema fallback, and one-per-day budget exhaustion logging.

## [2.10.16] — 2026-07-18

### Added
- Added replay queue-ahead data, trade prints, market-impact controls, and deterministic simulation fixtures.

## [2.10.15] — 2026-07-18

### Changed
- Added portfolio VaR/Expected Shortfall telemetry, CAP pressure, and correlation-cluster reporting.

## [2.10.14] — 2026-07-18

### Fixed
- Added centralized hysteresis for direction and AI parameter changes.

## [2.10.13] — 2026-07-18

### Added
- Added cross-quote valuation checks, stablecoin haircuts, and conversion-fee accounting.

## [2.10.12] — 2026-07-18

### Changed
- Added multi-period walk-forward reports, purge/embargo, confidence intervals, and cost robustness.

## [2.10.11] — 2026-07-18

### Fixed
- Hardened STOP gap handling, OCO cancellation, and confirmed MARKET/IOC flatten fallback.

## [2.10.10] — 2026-07-18

### Added
- Added complete virtual-shadow evaluation and explicit AI-vs-baseline metrics.

## [2.10.9] — 2026-07-17

### Changed
- Added dashboard version and changelog links, persistent AI controls, and a compact account-balance view.

## [2.10.8] — 2026-07-17

### Fixed
- Fixed BrokenPipe shutdown handling, stale AI status reporting, and protected log redaction.

## [2.10.7] — 2026-07-17

### Added
- Added RAG document and retrieval schemas with future-data protection.

## [2.10.6] — 2026-07-17

### Fixed
- Allowed SQLite online backups to create temporary WAL/SHM files in the database directory.
- Published each database copy atomically after a successful backup.

## [2.10.5] — 2026-07-17

### Fixed
- Made executor shutdown pipe-safe, replaced ambiguous OCO status values, expanded secret redaction,
  and bounded AI rationale/output length.

## [2.10.4] — 2026-07-17

### Changed
- Added English copyright headers and the project maintenance policy.

## [2.9.0] — 2026-07-16

### Added
- Established the Ladder Dragon supervisor, adaptive ladder strategy, Risk Manager, dashboard,
  protected logs, and Raspberry deployment baseline.

### Verified
- Testnet/DRY defaults, fail-closed safety gates, and the baseline regression suite were established.
