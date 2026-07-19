# Changelog — Ladder Dragon

All notable changes are documented here. Releases use Semantic Versioning; every
section is dated and there is intentionally no `Unreleased` section.

## [2.10.81] — 2026-07-19

### Fixed
- LIVE worker startup now reconciles every ordinary nonterminal BUY and SELL
  intent against Binance before placing another order. Exchange-confirmed
  cancellations become terminal, while an UNKNOWN/PREPARED order confirmed
  absent by Binance becomes FAILED without manual SQLite changes.
- A previously confirmed SUBMITTED order that disappears at Binance remains a
  fail-closed condition and activates the execution halt.
- The guarded cancellation tool now records Binance cancellation responses in
  the order-intent journal, including partial fills that still require
  protection.
- The dashboard now publishes the supervisor's effective AI request, token,
  and cost limits instead of showing missing limits or reading the bot's
  private environment.
- Raspberry throttling telemetry is exported by the root watchdog as a small
  sanitized status file. The hardened dashboard can display `throttled=0x0`
  without access to `/dev/vcio`, and reports whether the watchdog timer is
  active and enabled.

### Verified
- Added regression tests for external cancellation, confirmed-absent UNKNOWN
  SELL, lost SUBMITTED fail-closed handling, partial cancellation, AI budget
  publication, sanitized throttling telemetry, and watchdog deployment.
- Targeted order-recovery, cancellation, dashboard, deployment, and worker
  recovery test suites pass.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -q` — all tests pass.
- `python3 -m compileall -q bin ladder_dragon FastAPI tests`, deployment shell
  syntax, `git diff --check`, and the tracked-secret scan pass.

## [2.10.80] — 2026-07-19

### Fixed
- Dashboard heartbeat now reports the age of `/run/mybot/ai_status.json` rather
  than presenting systemd service uptime as heartbeat age.
- The hardened dashboard receives the `www-data` supplementary group so it can
  read encrypted public backup metadata without gaining write access.
- A read-only USB view inside the dashboard systemd namespace is now labelled
  as namespace isolation instead of falsely reporting the host disk as RO.
- The latest live Binance order is shown as the last order while it remains
  open, even when the local intent journal contains an older entry.
- The trade-accounting regression test isolates `AI_DECISIONS_DB`; pytest can no
  longer write its synthetic unresolved fill to an operator's production AI DB.

### Verified
- Added regression assertions for heartbeat telemetry, backup group access,
  namespace-safe USB labelling, current-order display, and temporary AI DB use.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`.
- Dashboard/deployment syntax and `git diff --check`.

## [2.10.79] — 2026-07-19

### Security
- Managed services no longer enable automatic OCO/SELL handling for
  pre-existing holdings by default. Those balances may have been acquired
  outside Ladder Dragon or may have an unreconciled cost basis.
- Existing-holdings automation now requires the explicit service setting
  `BOT_SERVICE_AUTO_OCO_HOLDINGS=1`; invalid values stop startup. OCO attachment
  for new BUY fills remains enabled independently.

### Verified
- Added deployment regression coverage for the safe default, explicit opt-in,
  strict setting validation, and the absence of an unconditional
  `--auto-oco-holdings` argument.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`.
- Deployment shell syntax and `git diff --check`.

## [2.10.78] — 2026-07-19

### Fixed
- Signed updates now install root-owned runtime assets through a dedicated
  release helper read from the verified target checkout after fast-forward
  merge. This prevents the immutable previous updater from omitting files that
  were introduced by the new release.
- Fresh installation and update share the same runtime-assets manifest for the
  sanitized log exporter and watchdog executable, preventing their deployment
  paths from drifting.

### Verified
- Added regression coverage for post-verification asset installation order,
  root ownership/modes, and shared installer/updater use of the manifest.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`.
- Deployment shell syntax and `git diff --check`.

## [2.10.77] — 2026-07-19

### Fixed
- The sanitized log exporter is now installed as a root-owned runtime asset in
  `/usr/local/libexec/ladder-dragon` and executed by the system Python. It no
  longer depends on checkout file modes, virtualenv traversal, or access to the
  bot user's home directory.
- The log-export service now hides `/home` completely while keeping an empty
  capability bounding set. The installed exporter is included in encrypted
  configuration backups for disaster recovery.

### Verified
- Added deployment regression coverage for the installed exporter path,
  capability-free service, hidden home directories, updater/installer copying,
  and encrypted-backup inventory.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`.
- Deployment shell syntax and `git diff --check`.

## [2.10.76] — 2026-07-19

### Fixed
- The capability-free sanitized log exporter now receives only the configured
  bot user's supplementary group. This permits traversal of a bot-owned `0750`
  project tree without granting `CAP_DAC_OVERRIDE` or other capabilities.
- Raspberry installer and updater unit rendering now replace the log-export
  supplementary-group template with the actual deployment account.
- Backup inventory generation records memory as unavailable when the hardened
  service intentionally hides `/proc/meminfo`, instead of emitting a misleading
  `free` warning during a successful backup.

### Verified
- Added regression coverage for capability-free log export traversal, custom
  bot-user rendering, and restricted-proc backup inventory.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`.
- Deployment shell syntax and `git diff --check`.

## [2.10.75] — 2026-07-19

### Fixed
- The hardened backup service retains only the filesystem capabilities required
  to traverse the bot-owned project tree, read private backup sources, create
  SQLite WAL sidecars, and publish `www-data` manifests. Removing every
  capability in 2.10.73 caused systemd to fail before executing the backup
  script with status 126 on Raspberry Pi installations using a `0750` bot home.
- The existing filesystem namespace remains fail-closed: writes are still
  limited to `/var/lib/ladder-dragon`, the SQLite directory, and the configured
  external backup mount. `CAP_SYS_ADMIN` and ambient capabilities remain absent.

### Verified
- Added regression coverage for the backup service's exact minimal capability
  set and retained write-path restrictions.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`.
- `git diff --check`.

## [2.10.74] — 2026-07-19

### Changed
- The dashboard GitHub update indicator now uses distinct current, available,
  and unavailable colors. When an update is available, the highlighted badge
  links to the exact commit returned by the GitHub update check.

### Verified
- Added dashboard regression coverage for the update-state styling, safe GitHub
  link handling, and removal of stale links after an unavailable response.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`.
- `git diff --check`.

## [2.10.73] — 2026-07-19

### Security
- Panic-state, indicator, and gap-watchdog failures now block new BUY orders,
  emit structured safety-control records, and trip the persistent circuit
  breaker after a configurable consecutive-failure threshold in LIVE mode.
- The supervisor singleton now uses a process-lifetime nonblocking `flock` in
  the private runtime directory and exits before launching workers if the lock
  cannot be acquired.
- Fresh Raspberry installations verify the exact commit against the pinned
  release-signing fingerprint before project activation. Normal updates read
  trust only from root-owned `/etc/ladder-dragon/update-trust.conf`; environment
  overrides were removed.
- Unsigned emergency updates require a separate interactive, journaled,
  exact-SHA, one-use break-glass authorization.

### Fixed
- A failed old-OCO cancellation is reconciled against Binance before any
  replacement is created. Unknown or still-open state now halts execution and
  preserves the prior protection record.
- Automatic order CAP calculations use `Decimal` throughout. Missing or
  invalid balance data clears any stale positive CAP and fails closed at zero.
- Binance public transport redacts query strings from throttle and auth paths
  as well as signed transport paths; definitive non-retryable 4xx responses are
  never repeated.
- Supervisor shutdown no longer unlinks a shared lock inode while another
  process may be waiting on it.

### Verified
- Added regression coverage for panic escalation, singleton exclusion,
  Decimal Auto-CAP failure, uncertain OCO cancellation, public transport query
  redaction, and strict parsing of the root-owned update trust anchor.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` —
  253 tests pass.
- Python compilation, deployment shell syntax, and `git diff --check` pass.

## [2.10.72] — 2026-07-19

### Security
- Raspberry updates now require a valid GPG-signed commit from an explicitly
  pinned maintainer fingerprint; runtime and CI dependencies are installed
  from SHA-256 hash-locked requirement files.
- The updater and installer no longer execute `backup.env`, and service tuning
  arguments pass through a numeric allowlist that blocks execution, venue,
  credential, path, and script overrides.
- Dashboard state-changing requests now require same-origin JSON and a CSRF
  token. API-derived table values are escaped, internal exceptions are replaced
  with stable error codes, and rate limiting trusts `X-Real-IP` only from the
  authenticated loopback nginx proxy.
- Nginx now supplies a hash-based Content Security Policy, clickjacking,
  MIME-sniffing, referrer, and browser-permission protections. Managed systemd
  services received additional device, process, namespace, capability, clock,
  and syscall restrictions.
- GitHub Actions are pinned by commit SHA and scan the full history with
  Gitleaks and verified TruffleHog detectors. The local scanner now covers
  GitHub, Telegram, Slack, Google, provider-style, binary, and high-entropy
  credential candidates.
- The dedicated release-signing public key and its pinned full fingerprint are
  published with the release documentation for independent update trust.

### Fixed
- Fresh installation instructions and installer defaults now use `main`.
- Dashboard failures no longer return SQLite paths or raw exception messages.
- Definitive Binance business rejections are no longer retried or classified as
  lost acknowledgements. Rejected intents become `FAILED` without tripping the
  persistent circuit breaker, while genuine connection ambiguity remains
  fail-closed.
- Binance transport logs no longer include signed query strings, request
  signatures, or exception text that can contain a private request URL. The
  order journal also scrubs both new and historical signed URLs on open.
- Automatic holdings SELL placement stops the current ladder pass after a
  definitive filter rejection instead of silently attempting every remaining
  level.

### Verified
- Added regression coverage for privileged config parsing, CSRF/origin denial,
  CSP integrity, locked dependencies, full-history scanners, pinned Actions,
  extended systemd sandboxing, non-retried Binance business rejections, safe
  transport logging, and rejection state recovery without a false halt.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` —
  243 tests pass.
- `.venv/bin/python -m pip check` reports no broken requirements and
  `pip-audit --skip-editable` reports no known vulnerabilities.
- Python compilation, deployment shell syntax, locked-dependency dry-run,
  tracked-secret scan, and `git diff --check` pass.

## [2.10.71] — 2026-07-19

### Fixed
- Direction adaptation can no longer increase `target_buys` above the explicit
  operator `--target-buy-per-symbol` limit. The operator value is now a hard
  ceiling in every market regime, including LIVE canary operation.

### Verified
- Added fail-closed regression coverage for an UP-regime request of three buys
  under a one-buy operator ceiling, plus normal and invalid-boundary cases.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 231 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.70] — 2026-07-19

### Fixed
- Dashboard order-intent counts now treat `FAILED`, `EXPIRED`,
  `EXPIRED_IN_MATCH`, and `REJECTED` as terminal states instead of reporting
  them as pending exchange work.

### Verified
- Added a regression test proving terminal failures are excluded while a
  genuinely prepared intent remains pending.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 228 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.69] — 2026-07-19

### Fixed
- The current total account value in the 24-hour trading card now uses the
  same live Binance balance snapshot as the account-balances section. Symbol
  filtering remains limited to 24-hour PnL, so holdings such as ETH are no
  longer omitted from one total while appearing in the other.

### Verified
- Added a dashboard asset regression check requiring both total-value widgets
  to share `total_value_usdt` from the live balance snapshot.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 227 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.68] — 2026-07-19

### Fixed
- Removed the decorative emoji from the dashboard document title so browser
  tabs display only the product name and the configured favicon.

### Verified
- Updated the deployment asset regression test to require the plain dashboard
  title and reject reintroduction of the emoji.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 227 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.67] — 2026-07-19

### Fixed
- The trading dashboard now reports `STOPPED` when `mybot` is inactive and
  reads its configured venue, execution mode, symbols, and CAP range from the
  non-secret `.env.service` file when the runtime heartbeat is absent.
- Removed the unsafe display fallback that converted every non-USDT account
  balance, including dust and unlisted assets, into a synthetic `ASSETUSDT`
  trading symbol.
- The dashboard GitHub update checker now defaults to the canonical `main`
  branch, transparently migrates the former pre-release branch value, and
  gives stopped-service banners a distinct neutral style.

### Verified
- Added dashboard regression coverage for stopped service configuration,
  strict service-field allowlisting, and absence of balance-derived symbols.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 227 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.66] — 2026-07-19

### Fixed
- Added explicit ignore rules for SQLite `*.sqlite3-wal` and `*.sqlite3-shm`
  runtime sidecars, keeping Raspberry databases out of Git status without
  deleting or publishing live database state.

### Verified
- Added a regression test covering DB and SQLite3 WAL/SHM ignore patterns.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 224 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.65] — 2026-07-19

### Fixed
- Removed the obsolete updater requirement that `mybot` must be enabled.
  Maintenance updates now preserve an intentionally disabled LIVE service
  without forcing operators to arm it first.

### Verified
- The deployment regression test now rejects reintroduction of the obsolete
  autostart requirement.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 223 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.64] — 2026-07-19

### Fixed
- The LIVE-confirmation subprocess test now explicitly masks production `.env`
  confirmation and runtime-path values. Raspberry test runs therefore verify
  the intended argument-parser rejection instead of attempting to write under
  `/run/mybot/testnet`.

### Verified
- The regression test is executed with inherited production-like
  `BOT_LIVE_CONFIRMED=YES` and `BOT_TESTNET_RUN_DIR=/run/mybot/testnet` values.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — 223 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements; `pip-audit
  --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.63] — 2026-07-19

### Fixed
- The Raspberry updater now restores the exact pre-update active and enabled
  state of `mybot`, `pi-healthd`, and the watchdog timer instead of
  unconditionally starting a stopped LIVE bot and dashboard.
- The watchdog remains stopped when `mybot` was intentionally stopped before
  an update, preventing it from reviving LIVE execution after deployment.

### Verified
- Added a deployment regression test that rejects unconditional service starts
  and requires preservation of stopped services and watchdog state.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. BOT_RUN_DIR=/tmp/ladder-dragon-local-tests .venv/bin/python -m pytest -q` — 223 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements.
- `.venv/bin/python -m pip_audit --skip-editable` — no known vulnerabilities.
- Python compilation, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.62] — 2026-07-19

### Security
- Updated the dashboard stack to FastAPI 0.139.2 and Starlette 1.3.1.
- Updated packaging and test dependencies to patched releases, including
  setuptools 83.0.0, pytest 9.0.3, httpx2 2.7.0, and urllib3 2.7.0.

### Changed
- Replaced the dashboard logo and favicon with a transparent dragon icon while
  leaving the full documentation logo unchanged.

### Fixed
- Isolated the non-LIVE OCO fallback test from a host-level
  `BOT_LIVE_CONFIRMED=YES` value.
- Changed the AI dashboard security fixture to use current timestamps so it
  tests SHADOW behavior instead of stale-data degradation.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. BOT_RUN_DIR=/tmp/ladder-dragon-local-tests .venv/bin/python -m pytest -q` — 222 tests pass.
- `.venv/bin/python -m pip check` — no broken requirements.
- `.venv/bin/python -m pip_audit --skip-editable` — no known vulnerabilities.
- `python -m compileall`, deployment shell syntax, tracked-secret scan, and
  `git diff --check` pass.

## [2.10.59] — 2026-07-19

### Security
- Updated Python dependencies to patched releases for the current pip-audit advisories.
- CI now upgrades the build toolchain and audits dependencies with `--skip-editable`, so the local project is not incorrectly treated as a missing PyPI package.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass; `pip-audit --skip-editable` reports no known vulnerabilities.

## [2.10.58] — 2026-07-19

### Security
- Removed `key_start_bot.txt` and `docs/legacy-systemd-notes.txt` from every Git revision before publication.
- Added SPDX MIT headers to source and dashboard assets while retaining the project copyright notice.
- Added the complete Chart.js Contributors MIT license and deploy it with the vendored dashboard asset.

### Verified
- Secret scan over the rewritten history and tracked files — no high-confidence secrets found.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass.

## [2.10.57] — 2026-07-19

### Fixed
- Restored the executor MARKET-order path used by gap flattening, panic
  exits, and time-stops. The path now uses the shared idempotent order journal,
  reconciles uncertain acknowledgements, and fails closed when flattening is
  not confirmed.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass.
- `git diff --check` passes.

## [2.10.56] — 2026-07-19

### Added
- Added a regression test that compares the canonical product version with
  README and the latest dated CHANGELOG heading and rejects `Unreleased`.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass.
- `git diff --check` passes.

## [2.10.55] — 2026-07-19

### Changed
- Vertically aligned the dashboard logo, title, refresh status, version,
  changelog link, and GitHub status in the header.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass.
- `git diff --check` passes.

## [2.10.54] — 2026-07-19

### Changed
- Added explicit independent-project and Binance trademark language.
- Added `SECURITY.md`, `CONTRIBUTING.md`, `TRADEMARKS.md`, and
  `THIRD_PARTY_NOTICES.md` for public maintenance and license clarity.
- Vendored Chart.js and removed the Google Fonts/CDN dashboard requests; the
  Raspberry installer and updater now deploy the local chart asset.
- Added weekly Dependabot checks for Python dependencies and GitHub Actions.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass.
- `python3 deploy/scan_tracked_secrets.py` — no tracked high-confidence secrets.
- `git diff --check` passes.

## [2.10.53] — 2026-07-19

### Changed
- Removed the remaining internal dashboard style wording from source comments;
  switch behavior and visual styling are unchanged.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass.
- `python3 deploy/scan_tracked_secrets.py` — no tracked high-confidence secrets.
- `git diff --check` passes.

## [2.10.52] — 2026-07-19

### Changed
- Replaced the public contact details in README and copyright documentation with
  the project owner's LinkedIn profile to reduce unsolicited email exposure.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q` — all tests pass.
- `python3 deploy/scan_tracked_secrets.py` — no tracked high-confidence secrets.
- `git diff --check` passes.

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
- Added a public project contact link to README and
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
