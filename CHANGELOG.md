# Changelog — Ladder Dragon

All notable changes are documented here. Releases use Semantic Versioning; every
section is dated and there is intentionally no `Unreleased` section.

## [2.20.25] — 2026-07-23

### Fixed
- Filled-BUY recovery now passes the exact Decimal average fill price to the
  inventory-lot lookup before creating OCO protection. This removes a
  `NameError` that could leave startup correctly blocked after an offline BUY
  filled while the public IP was unavailable.

### Verified
- The executor-protection regression test exercises the real lot-lookup branch
  and verifies that OCO placement receives the resolved lot ID.
- The complete local suite passes with `490` tests; source compilation,
  numeric-boundary audit and `git diff --check` pass.

## [2.20.24] — 2026-07-23

### Fixed
- Dashboard heartbeat and watchdog alert tests now force a temporary or
  nonexistent maintenance path. A real Raspberry Pi intentional-stop marker
  can no longer alter test expectations or suppress fake watchdog alerts.

### Verified
- The four previously host-dependent tests pass with the real Pi maintenance
  marker active. The complete local and Raspberry Pi suites pass with `490`
  tests; source compilation and safety audits pass.

## [2.20.23] — 2026-07-23

### Fixed
- Split the signed soak unit into unprivileged report generation and a
  root-only signing step. The service can traverse the owner-only bot home
  without granting `CAP_DAC_OVERRIDE`, while the Ed25519 private key remains
  inaccessible to the trading user.
- The updater now creates the soak artifact directory as root with group-only
  write access for the bot service.

### Verified
- Deployment asset and systemd sandbox tests passed. The complete local suite
  passed with `490` tests; compilation, shell syntax, numeric-boundary,
  dependency and tracked-secret audits passed.

## [2.20.22] — 2026-07-23

### Added
- Added source-hashed archive backfill for expired prediction horizons.
  Companion metadata and SHA-256 must match, and every required one-minute
  aggregate-trade interval must exist before an outcome is recovered.
- Added SHADOW-only regime analytics for PANIC state, BUY distance, fill/TP
  rates, adverse movement and re-anchor edge across trend, range and panic.

### Changed
- Real execution telemetry now records exact quote-valued fill commissions.
  Replay validation compares fills, price, fee, slippage and latency and labels
  its queue model `L2_PRICE_LEVEL_FIFO_PROXY` with `exact_l3=false`.

### Verified
- Prediction, user-stream, replay and readiness regression tests passed,
  including hash mismatch, incomplete archive and unavailable-fee fail-closed
  cases.
- The complete local suite passed with `490` tests. Source compilation,
  numeric-boundary audit, shell syntax and `git diff --check` passed.

## [2.20.21] — 2026-07-23

### Added
- Added an explicit `INTENTIONALLY_STOPPED` maintenance state. The dashboard
  distinguishes it from failure, the supervisor keeps LIVE inert, and the
  watchdog suppresses restart alerts until an operator clears the marker.
- Added a 15-minute systemd soak audit that writes a host-local Ed25519-signed
  JSON artifact and sends English Telegram notifications only when its
  approval/check state changes.

### Fixed
- LIVE startup now verifies the exact Binance OCO list identity and both active
  SELL protection legs for every durably protected BUY before `RUNNING`.
- Public-IP guarding now requires matching fingerprints from two independent
  HTTPS hosts before accepting or blocking on a changed egress identity.
- Production soak approval now also requires LIVE Mainnet and a passing
  prediction statistical gate; missing runtime evidence fails closed.

### Verified
- `168` focused recovery, maintenance, IP, dashboard, deployment and soak tests
  passed. Shell syntax, source compilation and `git diff --check` passed.
- The complete local suite passed with `490` tests; the numeric-boundary audit
  reported no regressions.

## [2.20.20] — 2026-07-23

### Added
- Added a persistent, owner-only authentication resilience state. Binance
  retry deadlines now survive supervisor and Raspberry Pi restarts.
- Added a public-egress guard that persists only a SHA-256 fingerprint,
  not the address. A confirmed change enters `IP_BLOCKED`, sends an English
  Telegram warning and requires explicit operator acceptance after the Binance
  whitelist is updated.
- Added a read-only production soak report that cannot approve before the
  configured elapsed time, fresh RUNNING heartbeat, exact real lifecycles and
  minimum resolved prediction observations are all present.

### Fixed
- LIVE now reconciles every durable nonterminal exchange order before
  publishing `RUNNING`. Any executed BUY without verified protection remains
  in `RECOVERY_BLOCKED`; workers cannot start behind an ambiguous order.
- Prediction windows that are no longer reconstructable from retained bars
  terminate as `INSUFFICIENT_HISTORY` instead of remaining pending forever or
  being counted as `NO_FILL`. Re-anchor telemetry now reports actual proposed
  versus baseline fills, TP outcomes, net PnL edge and entry gap.
- Dashboard, updater and watchdog now distinguish a fresh fail-closed
  `AUTH_BACKOFF`, `IP_BLOCKED` or `RECOVERY_BLOCKED` process from healthy
  `RUNNING`, without creating a restart storm.

### Verified
- `112` focused authentication, recovery, prediction, dashboard, deployment
  and soak-report tests passed.
- The complete local suite passed with `477` tests. Numeric-boundary audit,
  `python3 -m compileall -q .` and `git diff --check` passed.

## [2.20.19] — 2026-07-23

### Fixed
- Definitive Binance authentication/IP rejections now keep the LIVE supervisor
  fail-closed in `AUTH_BACKOFF` instead of exiting into a ten-second systemd
  restart loop. Retries use bounded exponential intervals of 60, 120, 240,
  480 and at most 900 seconds.
- Authentication backoff refreshes sanitized runtime telemetry with BUY
  blocked. The Pi watchdog and updater accept that fresh fail-closed state
  without resetting the delay or claiming that trading is RUNNING.

### Verified
- `118` focused auth backoff, watchdog, updater, configuration, version and
  safety tests passed; the complete local suite passed with `468` tests.
- Numeric-boundary audit, `python3 -m compileall -q .` and `git diff --check`
  completed successfully.

## [2.20.18] — 2026-07-23

### Fixed
- The authenticated dashboard status test now uses a temporary AI runtime
  status path. Running the suite on a LIVE Raspberry Pi can no longer make the
  assertion depend on the production supervisor's current runtime state.

### Verified
- `79` focused dashboard isolation, prediction, re-anchor, version and
  deployment tests passed; the complete local suite passed with `465` tests.
- `python3 -m compileall -q .` and `git diff --check` completed successfully.

## [2.20.17] — 2026-07-23

### Fixed
- Prediction settlement now defines each horizon as one, five or fifteen
  complete future one-minute bars. Decisions taken between minute boundaries
  no longer leave every one-minute outcome permanently pending.
- The best adaptive BUY candidate can be constrained to 0.15% below market.
  Age, minimum movement, per-cycle step and count limits remain mandatory, and
  LIVE order changes remain blocked until the statistical APPLY gate passes.

### Verified
- `78` focused prediction, re-anchor, supervisor configuration, version and
  deployment tests passed; the complete local suite passed with `465` tests.
- `python3 -m compileall -q .` and `git diff --check` completed successfully.

## [2.20.16] — 2026-07-23

### Security
- Mainnet canary now builds Risk Manager paths only from its explicitly supplied
  environment. A fake or embedded caller can no longer inherit an unrelated
  ambient production halt, state or alerts path.
- Mainnet canary tests isolate all persistent risk paths under `tmp_path`, even
  when executed directly on a configured LIVE Raspberry Pi.

### Verified
- `118` focused canary isolation, Risk Manager, version and deployment tests
  passed; the complete local suite passed with `463` tests.
- `python3 -m compileall -q .` completed successfully.

## [2.20.15] — 2026-07-23

### Fixed
- Allow the first prediction SHADOW snapshot immediately after a fresh Linux
  boot. An absent throttle timestamp is no longer treated as monotonic time
  zero, which previously skipped collection while uptime was below 60 seconds.

### Verified
- The focused regression forces a ten-second monotonic uptime and records both
  strategy and hashed re-anchor decisions.
- Full local `pytest` passes all 462 tests with documented test risk-limit
  defaults; project-wide `compileall` and `git diff --check` pass.

## [2.20.14] — 2026-07-23

### Added
- Added a look-ahead-safe technical prediction layer for 1, 5 and 15 minute
  horizons with trend, volatility, momentum, volume, public taker-flow, L2
  spread/depth and market-regime features.
- Added an immutable SQLite SHADOW journal that resolves BUY fill, TP-before-STOP,
  exact net PnL after fee/slippage, adverse movement and fill time. Re-anchor
  candidates retain both the proposed and original BUY plans for paired
  counterfactual evaluation.
- Correlated each prediction with the sanitized executor PANIC state and
  debounce count so PANIC sensitivity can be evaluated against later outcomes
  instead of weakened from anecdotal cancellations.
- Added expanding walk-forward reporting and a fail-closed APPLY eligibility
  gate covering independent sample count, lower confidence bounds, paired
  baseline edge, Holm correction, four regimes, fill rate and drawdown.

### Fixed
- Prediction public reads run only after the deterministic worker launch and are
  rate-limited to one attempt per symbol per minute, so SHADOW collection cannot
  delay PANIC recovery or alter worker parameters.

### Safety
- Prediction has no order capability and always remains observation-only.
  Re-anchor APPLY now requires both an explicit operator setting and a passing
  statistical gate; missing or unreadable evidence falls back to SHADOW. No
  result can bypass Risk Manager, PANIC, circuit-breaker, reserve or exposure
  gates.
- Only closed bars at or before each immutable decision timestamp are accepted.
  Ambiguous same-bar TP/STOP outcomes resolve to STOP, and unavailable trade
  flow is explicitly marked unavailable instead of synthesized.

### Verified
- Full project `pytest` passes all 462 collected tests with the documented
  test risk-limit defaults. Project-wide `compileall`, focused prediction,
  counterfactual, walk-forward, stream, dashboard and re-anchor checks pass.

## [2.20.13] — 2026-07-23

### Fixed
- User Data Stream PING, PONG and data frames now persist a sanitized transport
  activity timestamp. The dashboard uses it for stale detection, preventing a
  quiet healthy connection from being marked stale solely because the JSON file
  or last order event is old.

### Verified
- Focused User Data Stream and dashboard-security tests pass; project-wide
  `compileall` also passes.

## [2.20.12] — 2026-07-23

### Fixed
- End the observation-only executor cycle immediately after a confirmed LIVE
  PANIC `ON` to `OFF` transition when no BUY remains to protect. The supervisor
  can now start a fresh executor and re-evaluate a replacement BUY without
  waiting for the old worker's full runtime window.

### Safety
- The recovery exit requires a verified transition, LIVE mode and an empty
  tracked-BUY set. Active or unevaluable PANIC state and any retained BUY fail
  closed; the replacement worker still re-runs preflight, Risk Manager,
  gap-watchdog, CAP, VWAP and exchange open-order checks.
- The restart decision consumes only current control state and tracked order
  identifiers; it receives no future market data, credential or secret input.

### Verified
- Focused PANIC recovery, safety-gate and supervisor lifecycle tests pass.
- Full project `pytest` passes all 452 collected tests; project-source
  `compileall` and `git diff --check` also pass.

## [2.20.11] — 2026-07-23

### Fixed
- Removed the blocking `/api/v3/myTrades` replay from the executor BUY startup
  path. Average-entry recovery now uses only locally verified exact lots, so
  third-asset commission conversion cannot delay a replacement BUY for minutes.
- Cached an unavailable legacy basis as an explicit fail-closed result. Legacy
  or incomplete inventory can no longer provide an average that releases panic.

### Added
- Published adaptive re-anchor mode, thresholds, per-symbol proposals and
  cumulative shadow/apply counters through the protected runtime status and
  read-only trading overview.
- Added dashboard rows for the effective re-anchor configuration, activity and
  latest proposed price change.

### Security
- Updated the dashboard CSP hash for the only allowed inline script. No secret,
  API credential or environment value is exposed by re-anchor telemetry.

### Verified
- Focused re-anchor, safety-gate, dashboard-security and deployment-asset tests
  pass with the documented test risk-limit defaults.
- Full project `pytest` passes all 450 collected tests; project-source
  `compileall`, CSP validation and `git diff --check` also pass.

## [2.20.10] — 2026-07-23

### Added
- Added an opt-in adaptive BUY re-anchor that compares existing unfilled BUYs
  with the current ladder using exact decimals, refreshes at most the configured
  count, and caps every upward replacement step.

### Safety
- Re-anchor remains `OFF` by default; `SHADOW` records candidates without
  cancellation. `APPLY` never cancels partially filled BUYs, SELLs or OCO legs,
  and never follows a falling ladder. A confirmed refresh
  gracefully restarts only that symbol's worker so the replacement uses the new
  immutable plan; panic, VWAP, CAP and the execution-cost profit floor remain
  authoritative.

### Verified
- The focused re-anchor, Risk, Executor protection, and deployment suites pass
  with the documented test risk-limit defaults isolated from the operator
  environment.
- Full project `pytest` passes all 446 collected tests; Python 3.10 source
  `compileall` and source-language validation also pass.

## [2.20.9] — 2026-07-23

### Changed
- Published the verified replay matching changes from 2.20.8 as a commit signed
  by the configured Ladder Dragon release key, allowing the Raspberry Pi
  updater to validate the exact release SHA without break-glass authorization.

### Verified
- `PYTHONPATH=. .venv/bin/python -m pytest -q` — 436 tests pass with the
  documented test risk-limit defaults isolated from the operator environment.
- Python 3.10 project-source `compileall` passes with an isolated bytecode cache.
- `git verify-commit` validates the release commit against fingerprint
  `808B9F52CB6C08901703EF7C113144122F1830A0`.

## [2.20.8] — 2026-07-23

### Fixed
- Conserved each public trade quantity across all replay orders and restricted
  maker queue consumption to the exact reported price level.
- Limited taker matching to venue arrival so a resting order cannot be
  reclassified as taker by a later depth movement.
- Shared each displayed L2 FIFO queue across same-price local orders and
  preserved the remaining public queue when the first local order is canceled.

### Changed
- Replay fills now include exact quote fees and an explicit `MAKER` or `TAKER`
  role. Replay validation consumes the typed fill contract.
- Backtest reports identify the archive model as
  `L2_PRICE_LEVEL_FIFO_ESTIMATE` with `exact_l3=false`; `--require-l3` fails
  closed for Binance public Spot depth.
- Ignored the local `.release-worktree` pointer so release tooling does not
  dirty the tracked project tree.

### Safety
- Existing public snapshot/diff recording, sequence-gap checks, SHA-256
  provenance, multi-regime readiness gates and real-outcome validation remain
  mandatory. The release does not manufacture L3 data or readiness evidence.

### Verified
- `PYTHONPATH=. .venv/bin/python -m pytest -q` — 436 tests pass with the
  documented test risk-limit defaults isolated from the operator environment.
- Python 3.10 project-source `compileall` passes with an isolated bytecode cache.

## [2.20.7] — 2026-07-21

### Fixed
- The shadow User Data Stream observer now reads WebSocket control frames and
  treats PING/PONG as transport activity. Quiet but healthy Binance sessions no
  longer reconnect every silent-session deadline because application `recv()`
  hid control frames.
- The idle deadline still forces a reconnect when neither data nor control
  frames arrive, while socket errors continue to fail over to REST polling.

### Safety
- User Data Stream remains notification-only. Every order event still triggers
  authoritative REST reconciliation before journal, inventory or protection
  state can change.

## [2.20.6] — 2026-07-21

### Fixed
- Supervisor ladder deduplication now formats prices with the shared exact
  exchange-tick helper. This removes a stale `_decimals_from_step` reference
  that caused a `NameError` and a systemd restart loop after AI context
  construction succeeded.
- A focused regression test executes the exact tick rounding and side-aware
  deduplication path reached immediately before executor startup.

### Safety
- Price keys are derived from `Decimal` exchange ticks rather than reconstructed
  float precision. Order CAP, reserve, Risk Manager and AI policy are unchanged.

## [2.20.5] — 2026-07-21

### Fixed
- The supervisor AI context now accepts every exact financial text field
  emitted by trade, portfolio and performance feature aggregation. This fixes
  executor startup failing before order recovery with an unexpected
  `net_realized_pnl_30d_text` constructor argument.
- A schema contract test now requires every aggregated feature field to exist
  in `MarketContext`, preventing the same class of drift from recurring.

### Safety
- The change does not enable AI order control: AI remains subject to its
  configured SHADOW/APPLY policy and Risk Manager remains authoritative.
- Restoring executor startup also restores authoritative REST reconciliation
  of nonterminal order intents and notification-only User Data Stream health.

## [2.20.4] — 2026-07-21

### Fixed
- The repeated LIVE risk cycle now computes price-shock changes entirely with
  finite `Decimal` values. This removes the remaining `Decimal - float`
  regression observed after a successful first risk snapshot.
- Shock detection now evaluates only configured trading symbols. Auxiliary
  whole-account valuation prices such as ETH or BNB can no longer enter the
  configured-symbol cooldown detector with mixed numeric representations.

### Safety
- Risk telemetry remains fail closed. The fix changes only numeric
  normalization and symbol scope; shock thresholds, cooldown behavior, CAP,
  reserve and order controls are unchanged.

### Verified
- Regression tests execute consecutive shock-detection cycles with mixed
  float/`Decimal` valuation maps and prove that only configured symbols can
  trigger a cooldown reason.

## [2.20.3] — 2026-07-21

### Fixed
- User Data Stream health snapshots are now rate-limited on disk while every
  frame still updates the in-memory state. Material connection, order and REST
  reconciliation counters remain immediately durable.
- Malformed and non-object WebSocket frames are counted and discarded locally
  instead of tearing down an otherwise healthy session.
- Silent sessions now reconnect after a configurable deadline rather than
  repeatedly pinging an unresponsive transport indefinitely.
- Signed WebSocket subscriptions now reuse the REST transport's synchronized
  Binance server timestamp instead of the raw Raspberry Pi wall clock.

### Observability
- Sanitized stream state and the dashboard expose `bad_frames` without storing
  frame contents, credentials or order payloads.
- Added documented controls for snapshot write frequency and silent-session
  timeout.

### Safety
- User Data Stream remains notification-only. REST reconciliation is still the
  sole source of truth and none of these changes can place, cancel, protect or
  account for an order.

### Verified
- Tests cover write throttling, malformed-frame containment, silent-session
  recovery, synchronized subscription timestamps and dashboard sanitization.

## [2.20.2] — 2026-07-21

### Fixed
- Risk snapshots now normalize every financial telemetry field and per-symbol
  exposure to finite `Decimal` values at construction time.
- Remaining BUY budget calculation now explicitly normalizes both limits and
  snapshot values before subtraction. This fixes the 2.20.1 LIVE regression
  where legacy float telemetry could raise `Decimal - float` and trigger the
  fail-closed risk gate.

### Safety
- Non-finite risk values are rejected before evaluation. Risk Manager remains
  fail closed, and the patch does not relax CAP, reserve, reconciliation or
  circuit-breaker behavior.
- No order-placement, OCO/STOP or AI policy behavior changes are included.

### Verified
- Regression tests cover legacy float telemetry, exact remaining-budget
  arithmetic and rejection of non-finite financial snapshots.

## [2.20.1] — 2026-07-21

### Changed
- Removed all 162 direct `float()` conversion calls from the supervisor,
  strategy worker and AI context. Indicator, timestamp and legacy JSON values
  now cross one documented finite-only compatibility boundary.
- The compatibility boundary rejects `NaN`, infinity and values outside the
  binary-float range instead of allowing non-finite telemetry into policy or
  strategy calculations.
- Marginal-risk CAP allocation now remains `Decimal` through weighting and
  per-symbol allocation. The previous numeric API is retained only as an
  explicit compatibility view.
- AST regression limits are now zero for supervisor, worker, AI context, order
  executor and protection executor. The isolated compatibility module is
  limited to exactly one conversion call.

### Safety
- Exact balances, CAP, exposure, filters, quantities and prices remain
  authoritative. The compatibility function is forbidden from financial state
  and is used only where indicator libraries or existing JSON contracts require
  a binary float.
- Order placement, OCO/STOP behavior, Risk Manager gates and AI SHADOW policy
  are unchanged.

### Verified
- All 418 tests pass. Numeric-boundary tests prove zero scattered conversions,
  finite-only compatibility behavior and exact marginal-risk CAP allocation.
- Compileall and diff whitespace checks pass.

## [2.20.0] — 2026-07-20

### Added
- Sanitized User Data Stream evidence schema 2 records exact side, order price,
  original quantity, cumulative quantity and cumulative quote for every
  observed order report. Hashed order references retain correlation without
  exposing exchange or client order identifiers.
- Replay validation compares terminal real order outcomes with replayed fill
  direction, fill ratio, price and latency. Reports are linked to their depth
  archive by SHA-256 and fail closed when coverage or accuracy is insufficient.
- Replay production readiness additionally requires an eligible validation
  report covering at least ten real orders.
- Added a read-only exact AI/RAG readiness audit covering closed real
  decisions, validated real RAG episodes, unresolved fills, realized edge
  confidence interval and stop rate.
- Added an AST numeric-boundary audit that prevents direct `float()` calls from
  returning to exact order and protection modules or exceeding the reduced
  analytics baselines.

### Changed
- AI context schema v3 exposes exact text companions for horizon returns,
  volume ratio, spread, order-book imbalance, decision price, risk-safe CAP and
  realized edge confidence interval.
- Market features, virtual-plan outcomes and realized AI aggregates use
  `Decimal` internally; numeric JSON fields remain compatibility boundaries.
- Direct `float()` calls are reduced from 130 to 125 in the supervisor and from
  19 to one in AI context. Executor order and protection modules remain at zero.

### Safety
- WebSocket evidence remains advisory: REST reconciliation is authoritative.
  Replay and AI gates return status 2 until natural production evidence is
  sufficient; the release does not fabricate depth archives or real RAG data.
- Existing order placement, hard CAP, OCO/STOP and AI SHADOW behavior is
  unchanged.

### Verified
- All 416 tests pass, including exact AI context, sanitized terminal execution
  outcomes, replay-to-real validation, AI/RAG readiness and numeric-boundary
  regression coverage.
- Compileall, diff whitespace and the tracked-secret scan pass.

## [2.19.1] — 2026-07-20

### Changed
- Dashboard polling now runs through one sequential scheduler, pauses while the
  tab is hidden, and aborts bounded requests after eight seconds.
- Filled-order endpoints return at most 500 rows per request and accept a
  bounded offset. The dashboard renders pages of 300 rows instead of rebuilding
  a 5,000-row table every eight seconds.
- The current sanitized log is capped at 256 KiB. The browser requests only its
  tail, displays at most 500 lines, and prevents overlapping log requests.
- AI usage and database aggregates are cached for 30 seconds. Closed-decision
  count and realized AI PnL are now calculated in SQLite rather than loading
  every historical `evaluation_json` row into Python.

### Fixed
- Response caching is bounded by key count, entry size and total estimated
  memory. Old rate-limit IP buckets are pruned instead of accumulating for the
  lifetime of the dashboard process.
- `pagehide` now cancels pending requests, clears timers and response cache, and
  destroys all Chart.js instances.

### Verified
- All 410 tests pass, including pagination, cache, timeout, visibility,
  rate-bucket pruning and log-retention coverage. Compileall, JavaScript and
  shell syntax, dependency consistency, PyPI vulnerability audit and the
  tracked-secret scan pass.

## [2.19.0] — 2026-07-20

### Added
- AI decisions now persist authoritative exact text for decision price and all
  settled horizon returns. Existing AI databases are backfilled in place while
  retaining REAL columns strictly as compatibility mirrors.
- AI trade, portfolio and realized-performance models expose exact text
  companions for all quote-currency fields used in accounting and policy
  telemetry.
- Exact depth-weighted conversion, stress-loss and marginal-risk helpers now
  preserve `Decimal` values until explicit analytics or JSON boundaries.

### Changed
- Realized AI PnL, average PnL, opportunity cost and confidence intervals are
  accumulated with exact arithmetic; public numeric fields remain compatible.
- Worker fee, breakeven and minimum profitable-exit calculations no longer pass
  through binary floats before LIMIT/OCO price construction.
- Supervisor cross-asset valuation, stablecoin haircut, per-symbol exposure,
  stress loss and gap-risk money use exact arithmetic. EMA/ATR/VWAP,
  confidence, timing and covariance analytics intentionally remain float.

### Safety
- The migration is additive and restart-safe for deployed Raspberry databases.
  Exact text is authoritative, and no existing AI decisions or compatibility
  columns are removed.
- REST reconciliation, exchange filters, hard CAP and AI SHADOW gates are
  unchanged.

### Verified
- Exact persistence, legacy backfill, settlement return, depth conversion and
  stress-loss tests cover values beyond binary-float precision.
- All 406 tests pass. Compileall, shell syntax, dependency consistency, PyPI
  vulnerability audit, tracked-secret scan and English-source checks pass.

## [2.18.1] — 2026-07-20

### Changed
- Telegram alerts now read only the current configured file. The retired
  `/etc/bot-alerts.env` path remains solely in installer/updater migration and
  compatibility-audit code.
- Fresh statistics databases automatically finish migration as exact-only
  storage without financial REAL columns or legacy synchronization triggers.
  A durable bootstrap marker safely resumes an interrupted empty bootstrap.
- Added preview-first commission revaluation using exact Binance trade IDs and
  matching side, price, quantity and timestamp. Apply requires a stopped
  service, two explicit confirmations and a separate mode-0600 SQLite backup.

### Safety
- Existing non-empty databases are never rebuilt by normal migration. Legacy
  or unpriced commission rows must resolve completely before any update, and
  inventory is recalculated in the same transaction.

### Verified
- All 404 tests pass. Compileall, shell syntax, dependency consistency, PyPI
  vulnerability audit, tracked-secret scan and English-source scan also pass.

## [2.18.0] — 2026-07-20

### Added
- Added an explicit, preview-first exact-only accounting retirement command.
  It requires a clean compatibility audit, a stopped-service operator workflow,
  a separate SQLite backup target and an exact confirmation phrase.
- Added compatibility telemetry for physical REAL columns and legacy
  synchronization triggers instead of presenting a clean exact-text audit as
  proof that the old storage has already disappeared.
- Added persistent User Data Stream counters proving periodic and event-woken
  authoritative REST reconciliation.

### Changed
- Current statistics, AI context, risk, PnL, supervisor and soak readers use the
  authoritative exact views while retaining a bounded old-schema read fallback.
- Install/update now migrates Telegram configuration to the current root-owned
  path and retires superseded service/nginx names after the encrypted backup and
  replacement assets exist.
- AI APPLY additionally requires validated real RAG episodes. User Data Stream
  production readiness now requires reconnect, order-event and event-to-REST
  evidence by default. Replay readiness also requires real execution samples.

### Safety
- Normal startup and 2.x updates do not drop SQLite columns. The exact-only
  rebuild is atomic, integrity-checked and leaves a mode-0600 online backup.
- The four intentional broad exception boundaries remain unchanged and tested;
  REST remains authoritative and AI remains advisory/SHADOW until evidence
  gates pass.

### Verified
- All 400 tests pass; compileall, shell syntax, dependency consistency, PyPI
  vulnerability audit and tracked-secret scan also pass.

## [2.17.0] — 2026-07-20

### Added
- Added an exact positive `Decimal` public-price reader while retaining a float
  compatibility view only for indicator consumers.
- Added a read-only User Data Stream soak audit with optional reconnect and
  order-event evidence gates.
- Extended compatibility retirement auditing to block on legacy or unpriced
  commission provenance and additional old Raspberry paths.

### Changed
- BUY planning, holdings management, emergency flatten and time-stop now use
  the exact public-price reader at their financial boundaries.
- AI portfolio exposure, reserve ratios, supervisor risk-safe CAP and LIVE
  preflight exposure now use `Decimal` internally; numeric JSON fields remain
  compatibility output only.
- User Data Stream snapshots retain only sanitized cumulative counters across
  short executor sessions. Dashboard telemetry now shows soak hours, sessions
  and disconnects in addition to freshness and event counters.

### Safety
- SQLite REAL columns, legacy migration paths and unverified SOL cost basis are
  deliberately not removed or fabricated. Their removal/import remains gated
  by deployed-host audits and exact exchange evidence.
- REST reconciliation remains authoritative regardless of User Data Stream
  soak status.

## [2.16.0] — 2026-07-20

### Added
- Added migration 006 with authoritative exact-accounting views and
  compatibility triggers that populate exact text for legacy writers.
- Added a read-only compatibility retirement audit for old configuration paths
  and incomplete exact-accounting rows.
- Added User Data Stream diagnostics for connection attempts and out-of-order
  events, including dashboard visibility.
- Added reconnect, duplicate/out-of-order and periodic REST-fallback regression
  coverage for the notification-only User Data Stream.

### Changed
- Binance account balances, reconstructed average entry and its worker cache now
  remain `Decimal` through the protection boundary.
- AI fill attribution no longer converts price, quantity, fee or slippage
  through binary float.
- Statistics, VWAP tuning and dashboard trade readers now select authoritative
  exact text values; numeric conversion remains only at public compatibility
  output boundaries.

### Compatibility
- Legacy REAL columns and old Raspberry migration paths remain available in
  2.x. They may be removed only in a future major release after the read-only
  compatibility audit passes on the deployed host.

## [2.15.0] — 2026-07-20

### Added
- Added exact text columns for AI fill price, quantity, fees, slippage and linked
  expected order price while retaining numeric compatibility columns.
- Added multi-archive replay readiness auditing for unique source hashes,
  multi-day coverage, low/normal/high volatility regimes and measured
  intent-to-`executionReport` latency.
- Added exact-decimal regression coverage for AI PnL, legacy FIFO reports and
  all executor order/OCO compatibility boundaries.

### Changed
- Converted realized AI PnL, opportunity cost, fees, slippage and the legacy
  standalone FIFO reporter to exact `Decimal` arithmetic.
- Removed every `float()` conversion from `executor_orders.py`,
  `executor_protection.py` and the worker's BUY/SELL/OCO submission paths.
- Replaced broad exception handling in statistics, cancellation, planning,
  ladder-map, VWAP autotune, ladder-runner and PnL helper CLIs with explicit
  operational/data error sets.
- Replay calibration schema 3 now records observed p95 mid-price volatility for
  auditable regime classification. Older schema 1/2 reports remain readable.

### Verified
- The remaining broad handlers are restricted by AST regression to four
  documented post-mutation or fail-closed safety boundaries.

## [2.14.0] — 2026-07-20

### Changed
- Preserved Binance quantity, tick, minimum quantity and minimum notional
  filters as exact decimal strings through order normalization.
- Converted supervisor balances, position limits, reconciliation tolerance,
  position flatten sizing, LIMIT/MARKET adapters and minimum-notional checks to
  `Decimal` at every financial decision boundary.
- Changed a position-flatten calculation failure to remain reduce-only instead
  of resuming normal BUY planning.
- Removed broad exception handlers from the supervisor and AI context. Open
  order visibility failures now propagate rather than being treated as an empty
  exchange order book.

### Verified
- Added exact-filter normalization coverage for sub-satoshi steps.
- Added an AST regression that permits broad exception handling only in the
  three documented fail-closed execution/protection boundaries.

## [2.13.1] — 2026-07-20

### Changed
- Replaced Cyrillic comments, docstrings, CLI help, diagnostic messages and
  dashboard fallback text with English maintenance text. Translated dashboard
  content remains available exclusively through the localization catalog.
- Dashboard dynamic fallback messages now use localization keys where an
  existing translation is available.

### Verified
- Added a repository regression that rejects Cyrillic text in Python, shell,
  HTML and JavaScript source files outside the explicit localization catalog.

## [2.13.0] — 2026-07-20

### Added
- Added sanitized correlation from each durable pre-POST order intent to its
  locally received `NEW executionReport`. Replay calibration can consume these
  samples as actual observed order acknowledgement latency while continuing to
  label public event receive timing as a network proxy.
- Added a least-privilege public depth recorder service and hourly systemd
  timer. It records 15-minute SOLUSDT samples across volatility regimes,
  retains seven days by default, uses an exclusive lock, and explicitly removes
  Binance and AI credentials before starting.
- Added dashboard User Data Stream freshness thresholds and explicit stale,
  reported-state and legacy cost-basis provenance fields.

### Changed
- LIMIT, MARKET, OCO, breakeven replacement, emergency flatten and time-stop
  quantity/price boundaries now use exact `Decimal` Binance filters in the
  production adapter. Legacy float callbacks remain only as an injected
  compatibility boundary.
- Replay now uses the event book's dynamic spread, advances a configurable
  fraction of queue position on depth cancellation, consumes queue with public
  trades, and scales impact by executed volume at the matched level.
- Narrowed noncritical parsing, subprocess and context-construction exception
  handlers in the supervisor. The two executor fail-closed safety boundaries
  remain intentional.

### Security
- OCO and MARKET mutations reject non-finite or sub-minimum Decimal values
  after final exchange-step rounding. Archive recording is isolated from
  trading credentials and writes only to its dedicated retained directory.
- Legacy SOL holdings remain unmanaged and visibly unverified; this release
  does not fabricate or automatically import their cost basis.

### Verified
- Added exact MARKET/OCO, sanitized execution-latency, stale User Data Stream,
  queue-cancellation, dynamic-impact and hardened systemd regressions.
- Python compilation and the complete local suite pass: 377 tests; dependency
  auditing reports no known vulnerabilities, `pip check` reports no broken
  requirements, and the tracked-secret scan is clean.

## [2.12.0] — 2026-07-20

### Added
- Added a public-only Binance Spot depth recorder that combines an official
  REST snapshot with contiguous 100 ms diff-depth and aggregate-trade streams.
  Archives and sanitized metadata are source-hashed and published atomically.
- Added User Data Stream health to the dashboard for every configured symbol,
  including connection age, event counts, reconnects and sanitized errors.
  The UI explicitly retains authenticated REST as the authoritative source.

### Changed
- BUY ladder planning and its final CAP boundary now use exact `Decimal`
  quantities, prices, notional values, free balance and remaining budget.
  Exchange-step rounding cannot lift an order above the operator, risk-safe or
  per-symbol CAP.
- Replay calibration schema 2 records whether latency comes from execution
  reports or public event receive timing. Public transit latency is identified
  as a proxy rather than presented as exchange order acknowledgement latency.
- Removed the remaining broad `except Exception` handlers from the dashboard's
  telemetry, database and read-only Binance boundaries; programming errors now
  remain visible while known external-data failures still degrade safely.

### Security
- Public depth recording never reads API credentials and aborts on a missing
  snapshot bridge, an invalid book, or any subsequent update-ID gap.

### Verified
- Added exact post-rounding BUY-CAP, depth continuity, archive provenance,
  calibration latency-source and sanitized dashboard stream-state regressions.
- A public SOLUSDT network smoke bridged the official snapshot to contiguous
  depth updates, retained an official aggregate trade and produced an eligible
  schema-2 calibration with `public_event_receive` latency.
- Python compilation and the complete local suite pass: 369 tests; dependency
  auditing reports no known vulnerabilities and the tracked-secret scan finds
  no high-confidence secret.

## [2.11.0] — 2026-07-20

### Added
- Added an opt-in Binance Spot User Data Stream SHADOW observer using the
  current signed WebSocket API subscription. `executionReport` events wake an
  authenticated REST query early; they never mutate orders, inventory, PnL or
  the order journal directly.
- Added bounded in-memory deduplication for partial and terminal order events,
  reconnect backoff, a secret-free health snapshot and explicit Mainnet/Testnet
  WebSocket endpoint selection.

### Security
- Periodic REST polling remains active when the stream is missing, duplicated,
  late, terminated or rejected. Stream failure cannot authorize an order or
  convert an unknown exchange state into success.
- Added pinned `websocket-client` hashes to Raspberry and CI lock files.

### Verified
- Added parser, identity, partial-fill, duplicate, HMAC request, endpoint,
  sanitized-state, rejection and REST-fallback regression tests.

## [2.10.100] — 2026-07-20

### Security
- The holdings SELL planner now retains Binance tick, step, minimum quantity
  and minimum notional values as exact decimals. Price guards,
  deduplication, allocation and the inventory decrement after an acknowledged
  order no longer depend on binary-float arithmetic.
- LIMIT submission rejects non-finite values and rechecks both minimum
  quantity and minimum notional after exchange-step rounding. A rounded order
  that still fails the filter cannot reach the signed mutation boundary.

### Verified
- Added high-precision regression tests for occupied-price deduplication,
  guarded SELL levels, final-slot inventory bounds and exact LIMIT payloads.

## [2.10.99] — 2026-07-20

### Changed
- GitHub CI now runs the complete test suite on every supported Python minor
  version: 3.10, 3.11 and 3.12. Dependency and full-history secret audits run
  once in a separate pinned job.
- Backtest JSON now records report schema, Ladder Dragon engine version, exact
  configuration, input/calibration SHA-256 values and the corrected
  `market_impact_bps` divisor of 10,000. Invalid impact values fail closed.

### Added
- Added `bin.audit_backtest_reports` to classify saved reports. Legacy reports
  with non-zero market impact return exit code 2 and must be regenerated;
  zero-impact legacy reports are identified as old but unaffected by this fix.
- The backtest CLI accepts explicit `--market-impact-bps` and optional
  `--output` while preserving JSON output on stdout.

### Verified
- Added report provenance, invalidation, CLI exit-code and market-impact range
  regression tests. Python compilation and the complete local suite pass: 354
  tests; the tracked-secret scan reports no high-confidence secret.

## [2.10.98] — 2026-07-20

### Security
- Legacy cost-basis reconstruction may seed only the exact prehistory quantity
  proven necessary by a negative running inventory. The unpriced seed must be
  fully consumed at a historical zero-inventory reset before any current FIFO
  lot can be imported.
- An unexplained current balance remainder is quarantined outside managed lots
  only when it is strictly below Binance `LOT_SIZE.stepSize`. A tradeable
  remainder, surviving unpriced lot, missing filter or changed live snapshot
  still fails closed.

### Added
- Cost-basis plans and import audit rows now record the prehistory quantity,
  quarantined dust and exact history-reset trade ID. Migration `005` adds the
  durable audit columns without changing existing imported lots.

### Verified
- Added regression coverage for fully consumed prehistory, sub-step dust
  quarantine, rejection at the tradeable step boundary and atomic persistence
  of the new audit evidence. Python compilation and the complete local suite
  pass: 349 tests.

## [2.10.97] — 2026-07-20

### Security
- Added a preview-first legacy holdings cost-basis import. It reconstructs FIFO
  lots from exact Binance trade IDs, order IDs and historical commissions,
  requires account-quantity agreement, writes a private hash-bound plan, and
  revalidates the complete live state before an atomic apply.
- Applying a basis requires two explicit confirmations and a stopped service.
  Any changed Binance state, incomplete history, unpriced commission or failed
  post-write coverage check rolls back; prior lots are archived rather than
  deleted.
- Exchange open-order, order-query and cancellation wrappers no longer convert
  transport or malformed-response failures into empty/successful results.
  Callers now receive the failure and retain their fail-closed behavior.
- Critical filled-BUY quantity, average price, balance, notional and guard
  comparisons use `Decimal`; conversion to float is limited to legacy callback
  boundaries. Protection diagnostics no longer emit raw transport exception
  text that could contain signed query data.

### Added
- Added raw/normalized Binance JSONL replay loading with strict depth sequence
  validation, archive SHA-256 provenance and eligibility-gated calibration for
  spread, slippage, participation, partial fills, latency and market impact.
- Backtests can consume eligible calibration reports and reject a mismatched
  archive hash. Daily candle timestamp units are detected correctly.
- Imported basis metadata persists the source history hash, plan hash, exact
  quantities, weighted average and last trade ID. Later fills recalculate from
  that verified baseline instead of overwriting it.
- Live FIFO lot synchronization now records both exchange trade/order
  provenance, includes quote-paid BUY commissions in unit cost, subtracts
  base-paid BUY commission, and consumes base-paid SELL commission quantity.
  Replaying a fill with the same exchange trade ID is idempotent.
- Added migration `004` for durable cost-basis import audit records; existing
  inventory-lot provenance columns remain upgraded idempotently by the shared
  inventory schema helper for compatibility with pre-migration databases.

### Fixed
- Replay matching now uses BUY-descending/SELL-ascending price-time priority,
  consumes each visible book level only once per event, and interprets market
  impact in actual basis points.
- Statistics and market read helpers catch explicit operational failures rather
  than arbitrary programming exceptions on critical execution paths.

### Verified
- Added regression coverage for commission-aware FIFO reconstruction, preview
  safeguards, stopped-service enforcement, truncation rejection, atomic
  rollback, imported-basis continuation, depth gaps, calibration provenance,
  price priority, one-time liquidity consumption and fail-closed recovery.
- Python compilation, shell syntax checks and the complete local suite pass:
  345 tests. `pip check` reports no broken project-environment requirements,
  `pip-audit --skip-editable` reports no known dependency vulnerabilities, and
  the tracked-secret scan reports no high-confidence secret.

## [2.10.96] — 2026-07-20

### Security
- Every LIMIT SELL and OCO now passes the shared
  `PERCENT_PRICE_BY_SIDE`/`PERCENT_PRICE` validator at the final order-layer
  mutation boundary. Strategy callers can no longer bypass the corridor check.
- Normal holdings SELL is authorized only when the complete Binance quantity is
  covered by positive-price FIFO lots carrying exchange-order provenance. Its
  profit guard uses the weighted verified lot average; a historical caller
  estimate cannot authorize or price legacy inventory.
- BUY target enforcement now fails closed when the open-order snapshot is
  unavailable instead of assuming that no BUY exists and risking duplicates.
- A MARKET response without a confirmed exchange order ID is now persisted as
  `UNKNOWN`, activates the halt callback, and propagates to the caller instead
  of being logged and converted to a false no-op success.
- Critical BUY/SELL/statistics paths no longer suppress arbitrary programming
  exceptions. Expected transport, input, arithmetic, filesystem and SQLite
  failures remain explicitly handled and logged.

### Added
- The isolated gap-watchdog drill now verifies a partial STOP residual cleanup,
  refuses a second SELL after an uncertain OCO-cancel acknowledgement, creates
  a persistent circuit halt, and proves that the halt survives restart.
- Cost-basis coverage reports expose the weighted lot average and reject
  quantity-only imports without source-order provenance.

### Changed
- README now distinguishes the safe fail-closed legacy holdings gate from the
  still-pending operator-reviewed cost-basis import workflow.

### Verified
- Added regression tests for final-boundary SELL rejection, verified weighted
  cost basis, unavailable BUY-order state, unconfirmed MARKET responses,
  partial gap cleanup and uncertain cancel acknowledgement.
- Python compilation and the complete local suite pass: 326 tests. The isolated
  gap drill reports `network_used=false` and all extended safety outcomes true.

## [2.10.95] — 2026-07-20

### Security
- Holdings SELL orders now load exact Binance symbol metadata and validate every
  candidate against `PERCENT_PRICE_BY_SIDE` (or `PERCENT_PRICE`) using the
  current `avgPrice` before any signed mutation. Missing, malformed, or stale
  filter inputs block SELL placement and enter the safety-control escalation
  path.
- Exchange-filter loading no longer keeps plausible defaults or suppresses
  malformed `exchangeInfo`; open-order reads required for holdings limits also
  fail closed instead of assuming an empty order list.
- The final BUY placement loop no longer silently suppresses arbitrary
  exceptions; expected transport/input failures emit a structured diagnostic,
  while unexpected programming failures propagate and stop execution.

### Added
- OCO protection records retain the two detailed exchange-verified leg IDs and
  types. A natural canary cycle is counted only after a fully `FILLED` exact
  TP/STOP leg closes its exact parent BUY; partial and unresolved fills cannot
  satisfy the promotion gate.
- Runtime telemetry, the trading API, and dashboard expose exact closed cycles,
  TP/STOP counts, the required total of three, and promotion readiness.
- Added a fully isolated `gap-drill` that proves OCO cancellation followed by a
  confirmed emergency flatten without network access, API keys, exchange
  orders, or commissions.

### Verified
- Added fail-closed filter, exact lifecycle attribution, offline gap-drill, and
  dashboard telemetry regression coverage.
- `python3 -m compileall -q .` and the full local test suite pass: 320 tests.
- The isolated `gap-drill` reports verified OCO cancellation and emergency
  flatten with `network_used=false`.

## [2.10.94] — 2026-07-20

### Fixed
- LIVE BUY notional now has a final fail-closed boundary immediately before the
  Binance mutation. VWAP, BEAR, strategy and AI adjustments are clamped to the
  smallest operator, dynamic Risk Manager, and per-symbol CAP.
- `--use-remainder-in-last` is ignored in LIVE and can no longer spend the free
  quote remainder above the final per-order CAP.
- The supervisor exports its immutable operator ceiling separately from the
  dynamically narrowed CAP, and the dashboard shows both values.
- Pre-existing inventory is explicitly classified as `legacy_unmanaged` when
  automatic holdings protection is disabled. Its gap-watchdog status is
  `not_applicable_legacy_inventory` instead of a misleading warning.

### Changed
- Promotion beyond the minimal SOLUSDT canary now requires at least three
  naturally completed, exactly linked `BUY fill -> OCO -> TP/STOP` lifecycles
  and a clean 24-hour observation window (48 hours preferred). The bounded paid
  acceptance drill remains one-shot per release and is not repeated to create
  performance data.

### Verified
- Added regression coverage for the smallest-authority CAP clamp, invalid CAP
  fail-closed handling, LIVE remainder prohibition, and legacy inventory gap
  classification.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 313 tests pass.
- Python compilation, dependency consistency, dependency audit, tracked-secret
  scan, shell syntax, CSP hash validation, and `git diff --check` pass.

## [2.10.93] — 2026-07-20

### Fixed
- An executor now removes a terminal zero-fill BUY from its protection watch
  list as soon as Binance reports `CANCELED`, `EXPIRED`, or `REJECTED`.
- Status telemetry now changes from `OCO:pending` to `OCO:not_needed` after
  supervisory TTL cleanup cancels an unfilled BUY; a genuinely protected fill
  continues to report `OCO:confirmed`.
- Temporary Binance read failures now return a clearly marked, bounded stale
  balance/open-order snapshot when one is available instead of periodically
  blanking the dashboard with HTTP 503.
- Browser refresh loops no longer overlap slow prior requests. A transient
  502/503 retains the previous values and marks them `STALE` rather than
  clearing the page.
- The dashboard service restarts after both clean and failed exits, while nginx
  converts upstream 502/504 failures into a stable JSON 503 response.

### Verified
- Added focused regression coverage for terminal zero-fill cleanup, prohibition
  of unnecessary OCO creation, and the `pending`/`confirmed`/`not_needed`
  status transitions.
- Invalid terminal execution quantities fail closed and remain in the protection
  watch list instead of being interpreted as a zero fill.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 308 tests pass.

## [2.10.92] — 2026-07-20

### Fixed
- PANIC debounce and cooldown state now persist in a private per-symbol runtime
  file, so restarting an executor cannot reset the first adverse confirmation.
- A raw PANIC signal blocks a new BUY immediately in LIVE. Debounce still
  controls escalation and holdings actions, but no longer creates a window for
  fresh exposure between the first and second confirmation.
- A malformed or unwritable PANIC state fails closed through the existing
  safety-control escalation path.

### Added
- Active BUY intents now retain a throttled, durable market-price observation
  range. PANIC and TTL cleanup logs include order age, configured TTL, limit
  distance from the market, minimum observed market price, execution quantity,
  and the exact cancellation reason.
- The bounded Mainnet canary now reads Binance account commission rates before
  mutation, estimates both MARKET legs, and refuses an estimate above its
  `0.02 USDT` default budget. The operator-set budget has an immutable
  `0.03 USDT` ceiling.
- Actual canary commissions are converted to USDT after cleanup and recorded in
  the private report. An unexpected budget breach fails closed with a persistent
  circuit halt.

### Changed
- The existing separately confirmed bounded Mainnet canary remains the only
  mechanism for forcing a `BUY -> fill -> OCO/STOP -> cleanup SELL` acceptance
  cycle. The passive production strategy is not made marketable merely to
  manufacture a fill.
- A successful bounded Mainnet canary is one-shot per product release, preventing
  accidental repeated BUY/SELL fees. The drill is documented as an acceptance
  expense rather than a profit-producing strategy.

### Verified
- Focused PANIC, recovery, cleanup, and bounded Mainnet canary regression tests
  pass, including restart persistence, immediate LIVE raw-signal
  blocking, corrupt-state fail-closed handling, and durable non-fill telemetry.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 302 tests pass.
- Python compilation, dependency consistency, and `git diff --check` pass.

## [2.10.91] — 2026-07-19

### Fixed
- The 24-hour dashboard no longer labels realized FIFO PnL as generic net
  earnings. It explicitly identifies that metric as realized FIFO PnL for SELL
  fills inside the selected window.
- The trading summary now displays the separate 24-hour trade cash flow already
  provided by the API: SELL proceeds minus BUY notional and fees in that window.

### Changed
- Portfolio value change, realized FIFO PnL, and trade cash flow are presented
  as three independent values with distinct identifiers, help text, colors, and
  localized labels.

### Verified
- Added API and dashboard regression assertions for all three accounting
  measures and their independent data bindings.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 294 tests pass.
- Python compilation, deployment shell syntax, CSP integrity, dependency
  consistency, `pip-audit`, `git diff --check`, version consistency, and the
  tracked-secret scan pass.

## [2.10.90] — 2026-07-19

### Fixed
- PANIC now immediately cancels every remaining open BUY created by the active
  executor instead of waiting for the normal order TTL.
- A lost or nonterminal Binance cancellation response now activates the
  persistent execution halt rather than assuming that exposure disappeared.
- A cancelled partial BUY remains `PROTECTION_PENDING` and continues through
  the existing OCO/STOP attachment path; only zero-fill cancellations leave
  the protection queue.

### Verified
- Added regression coverage for zero-fill cancellation, partial-fill
  protection handoff, and fail-closed handling of an uncertain cancel result.
- Full Raspberry-compatible regression, compilation, shell syntax, dependency,
  audit, secret-scan, and version-consistency checks pass.

## [2.10.89] — 2026-07-19

### Fixed
- The dashboard no longer labels the 24-hour mark-to-market portfolio value
  change as net earnings. It now shows `Portfolio value change` and realized
  `Net earnings` as independent metrics.
- FIFO realized PnL now deducts the proportional SELL commission in addition
  to the BUY commission embedded in lot cost. The API field `net_pnl_usdt`
  therefore represents realized trading PnL after both sides' fees.

### Added
- The trades summary API exposes `portfolio_change_usdt` explicitly and reports
  the realized calculation method as `fifo-net-fees`.
- Added localized portfolio-change labels for every supported dashboard
  language and regression coverage for the UI/API separation and fee math.

### Verified
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 291 tests pass.
- Python compilation, deployment shell syntax, `git diff --check`, dependency
  consistency, `pip-audit`, and the tracked-secret scan pass.

## [2.10.88] — 2026-07-19

### Fixed
- Auto-CAP balance telemetry now distinguishes the exchange's total free USDT,
  the protected reserve, and the amount spendable after that reserve. The
  former ambiguous `[BAL] USDT free` label no longer presents post-reserve funds
  as the full account balance.
- Auto-CAP threshold and allocation messages consistently use
  `spendable_after_reserve`; monetary calculations and safety limits are
  unchanged and continue to use `Decimal`.

### Verified
- Added exact regression assertions for normal allocation and the fail-closed
  below-threshold log message.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 289 tests pass.
- Python compilation, deployment shell syntax, `git diff --check`, dependency
  consistency, `pip-audit`, and the tracked-secret scan pass.

## [2.10.87] — 2026-07-19

### Fixed
- Removed the final compatibility reference to the retired pre-release Git
  branch from dashboard code and tests. GitHub update checks are now pinned to
  `main` and cannot be redirected by a stale dashboard environment value.
- The Raspberry installer now rejects every non-`main` branch locally before
  cloning or fetching. Reusing an obsolete migration command therefore returns
  a clear validation error instead of failing later on a missing remote ref and
  entering rollback.

### Changed
- Updated the project status with the successful bounded Mainnet canary: real
  BUY fill, verified OCO TP/STOP legs, journal reload reconciliation, exact
  cleanup SELL, zero residual base quantity, no open orders, and no circuit
  halt.

### Verified
- Added regression coverage for the canonical installer branch and for a
  dashboard environment value being unable to redirect release checks.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 288 tests pass.
- Python compilation, deployment shell syntax, `git diff --check`, dependency
  consistency, `pip-audit`, the tracked-secret scan, and a full tracked/worktree
  search for the retired branch name pass.

## [2.10.86] — 2026-07-19

### Fixed
- The bounded Mainnet canary no longer stores its singleton lock in
  `/run/mybot`, because systemd removes that runtime directory when `mybot` is
  stopped as required by the canary. The private `0600` lock now lives under
  the project-owned `.runtime` directory and relative paths are rooted at the
  project independently of the current working directory.
- Lock creation and acquisition failures now return a structured fail-closed
  result instead of an unhandled permission traceback. No Binance request is
  attempted when the lock cannot be acquired.

### Verified
- Added regression coverage for the project-rooted default lock, private file
  mode, and conversion of permission failures to a controlled runtime error.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 287 tests pass.
- Python compilation, deployment shell syntax, `git diff --check`, dependency
  consistency, and the tracked-secret scan pass.

## [2.10.85] — 2026-07-19

### Added
- Added a separate bounded Mainnet acceptance canary for `SOLUSDT`. It performs
  a real `MARKET BUY -> verified OCO -> journal reload -> cleanup SELL` cycle,
  cannot exceed `10 USDT`, preserves the configured reserve, and attributes the
  lifecycle through isolated client IDs, a private journal, and an NDJSON report.

### Security
- The canary requires the normal LIVE confirmation plus two canary-specific
  confirmations, refuses an active bot/watchdog, existing SOL orders, unsafe
  clock/filter/account state, prior unresolved production or canary intents,
  or a circuit halt. OCO prices are checked locally against Binance
  `PERCENT_PRICE`/`PERCENT_PRICE_BY_SIDE` before submission.
- A post-BUY failure attempts exact reconciliation and cleanup, creates a
  persistent manual-reset halt, and never starts the normal trading service.
  The shared OCO lifecycle now verifies `ALL_DONE` after cancellation and marks
  an exactly flattened parent intent `CLOSED`.

### Verified
- Added offline regression coverage for strict Mainnet origin validation,
  confirmation and service gates, the hard notional ceiling, exact BUY/OCO/
  cleanup attribution, private reporting, and persistent halt on an
  unrecoverable post-BUY OCO state.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 284 tests pass.
- Python compilation, deployment shell syntax, `git diff --check`, dependency
  consistency, tracked-secret scanning, and `pip-audit` pass with no known
  vulnerabilities in auditable dependencies.

## [2.10.84] — 2026-07-19

### Fixed
- Supervisor and dashboard now resolve `AI_CONTROL_FILE` through one canonical
  project-root helper. The default no longer points inside `bin/FastAPI`, and a
  relative configured path no longer depends on the process working directory.
- The dashboard AI switch and supervisor now always operate on the same private
  control file while absolute operator overrides remain supported.

### Verified
- Added regression coverage for default, relative, absolute, and cwd-independent
  AI control paths plus a deployment assertion that both processes use the
  shared resolver.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 272 tests pass.
- Python compilation, deployment shell syntax, `git diff --check`, dependency
  consistency, and the tracked-secret scan pass.

## [2.10.83] — 2026-07-19

### Fixed
- The updater now verifies that each service's pre-update autostart policy is
  preserved instead of requiring `mybot` and the dashboard to be enabled.
  An intentionally disabled but active canary no longer turns a successful
  update into a false failure.
- The trading process now exports sanitized order-journal counters and latest
  safe order fields in its private runtime status. The dashboard consumes that
  snapshot instead of requiring write-capable access to SQLite WAL/SHM files.
- Trading overview telemetry now identifies whether journal data came from the
  live runtime or the compatibility database reader.

### Verified
- Added regression coverage for runtime journal aggregation, safe dashboard
  consumption, and preservation of enabled and disabled service policies.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 270 tests pass.
- Python compilation, deployment shell syntax, `git diff --check`, dependency
  consistency, and the tracked-secret scan pass.

## [2.10.82] — 2026-07-19

### Fixed
- The watchdog runtime directory is now preserved between oneshot executions,
  so its sanitized `host-health.json` remains available to the hardened
  dashboard and Raspberry throttling no longer appears unavailable after a
  successful probe.
- Trading overview responses now distinguish an unavailable order-intent
  journal from real zero counters. The dashboard shows dashes and the safe
  diagnostic reason instead of falsely reporting zero cancelled or pending
  intents.

### Verified
- Added deployment coverage for persistent watchdog telemetry and dashboard
  regression tests for available and unavailable order-journal states.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q`
  — all 267 tests pass.
- Python compilation, deployment shell syntax, CSP integrity,
  `git diff --check`, and the tracked-secret scan pass.

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
