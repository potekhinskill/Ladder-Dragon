# Changelog — Ladder Dragon

All notable changes are documented here. Releases use Semantic Versioning; every
section is dated and there is intentionally no `Unreleased` section.

## [2.20.169] — 2026-08-08

### Added
- Backup status now identifies one archive by name, size, and SHA-256.
- Dashboard validation rejects missing, legacy, stale, or inconsistent backup evidence.

### Changed
- Local, external, and dashboard archive copies now use verified temporary files and atomic publication.
- Backup status files now use schema version two and atomic publication.

### Fixed
- An encrypted file name alone can no longer produce a successful dashboard backup status.
- A newer unverified archive now changes dashboard backup status to `unknown`.

### Security
- Encrypted archives remain private until checksum verification and atomic publication complete.
- The dashboard does not read backup plaintext or decryption keys.

### Verified
- Complete project, documentation, backup, dashboard, and deployment tests pass.

## [2.20.168] — 2026-08-08

### Added
- SHADOW reports now show a diagnostic cohort for active candidate entries.
- The diagnostic cohort excludes `NO_TRADE` rows and cannot approve APPLY.

### Changed
- Approval still compares each complete candidate against the always-active baseline.
- Prediction analytics use the latest 1,000 decisions per candidate.
- Raw prediction decisions and outcomes remain append-only.
- Walk-forward eligibility now uses one linear chronological pass.

### Fixed
- Prediction reports no longer require an unbounded SQLite temporary sort.
- Dashboard signed reads now compensate for the Binance server clock offset.
- A Binance `-1021` response causes one clock refresh and one read-only retry.
- Missing historical candles no longer use the current price as historical evidence.

### Security
- Dashboard Binance requests remain read-only and use bounded, secret-safe responses.
- HALT, SHADOW, CAP, and all execution approvals remain unchanged.

### Verified
- Complete project, documentation, prediction, dashboard, and transport tests pass.

## [2.20.167] — 2026-08-06

### Changed
- User Stream readiness now uses the `transport-stability-2026-08-v4` epoch.
- The audit reports idle, controlled, total, and transport-failure reconnects separately.

### Fixed
- Expected idle reconnects no longer fail the transport-stability rate gate.
- A fresh `RISK_PENDING` heartbeat no longer causes a watchdog restart.

### Security
- HALT and SHADOW remain unchanged, and REST remains authoritative.
- Historical v1, v2, and v3 epoch evidence remains append-only.

### Verified
- User Stream, watchdog, deployment, documentation, and complete project tests pass.

## [2.20.166] — 2026-08-05

### Added
- The User Stream service now accepts one controlled reconnect through `SIGUSR1`.

### Changed
- Signal handling only schedules the drill. The service loop closes the notification socket safely.

### Security
- REST remains authoritative, and the command does not restart the service or change orders.

### Verified
- Controlled reconnect, signal wiring, User Stream, documentation, and complete project tests pass.

## [2.20.165] — 2026-08-05

### Changed
- User Stream readiness now uses the `transport-stability-2026-08-v3` epoch.
- The new epoch starts after signed Binance authentication and IP Guard recovery.

### Fixed
- Authentication-failure reconnect churn no longer contaminates the current stability denominator.

### Security
- The observer preserves all v1 and v2 counters and append-only epoch evidence.
- The release does not remove HALT or enable APPLY.

### Verified
- Epoch migration, evidence retention, User Stream, documentation, and complete project tests pass.

## [2.20.164] — 2026-08-05

### Changed
- Binance authentication alerts now use one incident identity across signed endpoints.
- Failed Telegram delivery retries after one minute instead of entering the success cooldown.

### Fixed
- The bot and User Stream services now receive Telegram configuration through systemd.
- An unreadable root-owned configuration directory no longer suppresses authentication alerts.

### Security
- Alert messages keep credentials, signatures, public addresses, and query strings out of diagnostics.
- Authentication failure still blocks BUY and all trading mutations.

### Verified
- Telegram delivery, cooldown, service asset, documentation, and complete project tests pass.

## [2.20.163] — 2026-08-05

### Changed
- The active SHADOW contour now compares nine focused version-three candidates.
- Candidates use maker-only execution, optional RANGE entry, and 8-to-15-minute BUY lifetimes.
- Deep-entry variants test 30, 40, and 50 basis points with one authoritative TP floor.

### Fixed
- New candidates never pull a BUY closer than the untouched baseline price.
- New semantic identifiers keep version-two evidence outside the active gate.

### Security
- Every new candidate remains SHADOW-only and cannot change an order.
- HALT, CAP, Risk Manager, and execution permissions remain authoritative.

### Verified
- Prediction experiment, SHADOW isolation, documentation, and complete project tests pass.

## [2.20.162] — 2026-08-05

### Changed
- User Stream readiness now uses the `transport-stability-2026-08-v2` epoch.
- Current documentation identifies the v2 epoch and its approval requirements.

### Fixed
- Authentication-failure reconnect churn no longer contaminates the repaired transport soak denominator.

### Security
- The observer preserves the complete v1 epoch and every lifetime counter.
- The release does not remove HALT or change SHADOW, CAP, or execution permissions.

### Verified
- Epoch migration, User Stream, documentation, and complete project tests pass.

## [2.20.161] — 2026-08-05

### Changed
- The dashboard uses separate notices for `AUTH_BACKOFF` and `IP_BLOCKED`.

### Fixed
- A fresh `AUTH_BACKOFF` heartbeat now displays its operator action.
- Runtime warnings no longer depend on the last deployment-status record.

### Security
- The notice contains no public address, credential, balance, or signed request data.
- Stale fail-closed heartbeats do not display a current authentication warning.

### Verified
- Dashboard presentation, asset, security, and complete project tests pass.

## [2.20.160] — 2026-08-04

### Changed
- Changed-IP authentication recovery now performs one signed read each minute.
- Runtime diagnostics describe Binance code `-2015` as an authentication rejection.

### Fixed
- A 15-minute generic backoff no longer delays recovery after an allowlist update.

### Security
- Automatic recovery still requires signed Binance success and fresh two-source IP consensus.
- Recovery never removes HALT or changes SHADOW, CAP, or execution permissions.

### Verified
- Authentication, IP Guard, documentation, and complete project tests pass.

## [2.20.159] — 2026-08-04

### Changed
- Runtime and CI environments now use `cryptography 50.0.0`.

### Fixed
- The dependency audit no longer reports `PYSEC-2026-3552` from `cryptography 49.0.0`.

### Security
- Hashed Raspberry Pi and CI locks now require the fixed cryptography release.

### Verified
- Dependency audit, the complete pytest suite, and the release harness pass.

## [2.20.158] — 2026-08-04

### Changed
- The watchdog uses the shared alert cooldown for repeated bot-health incidents.

### Fixed
- An unresolved bot failure now sends another Telegram alert after the cooldown.

### Security
- Repeated alerts keep credentials and message bodies outside process arguments.

### Verified
- Focused watchdog tests, the complete pytest suite, and the technical English check pass.

## [2.20.157] — 2026-08-03

### Changed
- Post-deployment log review is scoped to Ladder Dragon services and sanitized application logs.

### Fixed
- Removed Raspberry Pi host-specific `atop` and `rtl_tcp` management from the product updater.

### Security
- Product deployment no longer starts or disables unrelated host services.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.156] — 2026-08-03

### Changed
- Runtime asset installation repairs the exact failed Debian `atop` service.
- Installation disables the exact failed `rtl_tcp` service when no Realtek USB device exists.

### Fixed
- A missing `/var/log/atop` directory no longer leaves `atop.service` failed.
- An unused RTL-SDR listener no longer remains enabled without its hardware.

### Security
- Modified operator units are never changed by this host cleanup.
- The disabled RTL-SDR unit remains installed for explicit future reactivation.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.155] — 2026-08-03

### Added
- User Stream readiness now uses an immutable, versioned soak epoch.
- Audit output keeps separate current-epoch and lifetime counters.

### Changed
- The dashboard shows the current soak epoch duration for each connected account stream.

### Fixed
- Historical reconnect churn no longer blocks a new reviewed stability period forever.

### Security
- Epoch evidence is append-only, bounded, sanitized, and validated before readiness can pass.
- Damaged epoch evidence blocks approval without disabling authoritative REST reconciliation.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.154] — 2026-08-03

### Changed
- Deployment removes the obsolete packet-idle check from the hardware watchdog.
- Encrypted backups now include the hardware watchdog configuration.

### Fixed
- Normal gaps in received Wi-Fi packets no longer produce repeated system warnings.

### Security
- The hardware watchdog remains active after the configuration change.
- Network recovery continues through the route, Internet, and heartbeat watchdog.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.153] — 2026-08-03

### Changed
- Runtime asset installation now retires the known legacy statistics synchronization units.
- The repository now ignores the local authentication resilience state file.

### Fixed
- A removed `stats_sync.sh` no longer causes a failed service every two minutes.
- Runtime authentication evidence no longer appears as an untracked checkout file.

### Security
- Unit retirement rejects a same-name unit when its command or timer target differs.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.152] — 2026-08-03

### Changed
- Worker timing now exposes only the active event-driven countdown.

### Fixed
- Removed the unused sleep-based `trading_seconds` generator and its obsolete test contract.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.151] — 2026-08-03

### Added
- User Stream soak output now includes cumulative reconnects per observed hour.
- The audit CLI exposes `--maximum-reconnects-per-hour` with a safe default of `1`.

### Fixed
- A long-lived but chronically reconnecting stream no longer passes readiness.
- Calendar age alone can no longer represent connection stability.

### Security
- Non-finite, negative, or exceeded reconnect limits fail closed.
- Negative persisted reconnect counters make the snapshot unreadable.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.150] — 2026-08-03

### Changed
- Order planning now exposes only the active Decimal API.
- Worker runtime imports only Decimal planning services.

### Fixed
- Removed 257 lines of unused parallel float planning code.
- Removed the obsolete float planning test and compatibility imports.

### Security
- A boundary regression prevents reintroduction of the removed float financial API.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.149] — 2026-08-03

### Changed
- Exact-only accounting retirement now requires the standard stopped-runtime evidence.
- The command reference lists every retirement mutation boundary.

### Fixed
- APPLY now rejects missing stopped confirmation and a fresh `RUNNING` heartbeat.
- The runtime gate executes immediately before the irreversible retirement call.

### Security
- Preview remains read-only, while APPLY fails closed before any retirement database mutation.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.148] — 2026-08-03

### Changed
- Execution, protection, and dashboard code now use one conservative Spot fee default.
- The example configuration defines `BOT_FEE_PCT=0.001` explicitly.

### Fixed
- Default breakeven protection now covers a 0.2% round-trip fee instead of 0.15%.
- Invalid fast-market numeric environment values now produce safe parser diagnostics.

### Security
- An account fee discount requires an explicit operator configuration.
- Parser diagnostics identify the invalid setting without printing its value.

### Verified
- The complete pytest suite and technical English check pass.

## [2.20.147] — 2026-08-03

### Changed
- Python Testnet entry points now assign the complete isolated state-path set.
- Missing Testnet variables use the same safe defaults as the managed service wrapper.

### Fixed
- Direct Testnet supervisor, risk control, and soak commands cannot retain Mainnet paths silently.
- Circuit-breaker files now always follow the selected Testnet runtime directory.
- Managed startup rejects collisions before database migration begins.

### Security
- Testnet and Mainnet path collisions block execution before environment mutation.
- Bash and Python independently enforce the same isolation boundary.

### Verified
- Ten focused venue, supervisor, and deployment tests pass.

## [2.20.146] — 2026-08-03

### Changed
- Read-only symbol fallback now uses the exact-accounting quote vocabulary.
- The parser supports known three-, four-, and five-character quote assets.

### Fixed
- ETHBTC no longer becomes the invalid asset pair `ET` and `HBTC` during metadata failure.
- Holdings logic can no longer derive a false zero balance from that split.

### Security
- Unknown quote suffixes fail closed instead of producing guessed asset names.
- Order placement still requires authoritative exchange filters.

### Verified
- Focused executor-market and module-boundary tests pass.

## [2.20.145] — 2026-08-03

### Changed
- Fast-market streaming now subscribes only to book ticker, aggregate trade, and full depth data.
- Strategy indicators continue to use the canonical REST candle workflow.

### Fixed
- Workers no longer calculate and retain unused stream EMA, ATR, and minute VWAP values.
- The public market snapshot no longer exposes fields without an active consumer.

### Security
- Fixed decision thresholds remain unchanged; this release cannot expand trading risk.
- Market freshness, spread, movement, sequence, and economic gates remain fail closed.

### Verified
- Focused market-stream and fast-market safety tests pass.

## [2.20.144] — 2026-08-03

### Changed
- Full depth snapshots can repeat their update identifier and refresh market state.
- Each WebSocket connection starts with new sequence and freshness evidence.

### Fixed
- One reordered depth snapshot no longer blocks fast-market decisions permanently.
- Reconnects cannot compare a new session with an obsolete depth identifier.

### Security
- An older frame still blocks BUY until a valid full snapshot arrives.
- A reconnect requires new book and depth frames before market readiness returns.

### Verified
- Ten focused market-stream tests pass, including duplicate, recovery, and reconnect cases.

## [2.20.143] — 2026-08-03

### Changed
- Prediction archive loading now requires nondecreasing aggregate-trade timestamps.
- Equal millisecond timestamps remain valid in their authenticated archive order.

### Fixed
- Unsorted archive rows can no longer corrupt minute-bar open and close values.
- Incorrectly concatenated sessions now fail with the exact offending line.

### Security
- Invalid chronology blocks backfill before Prediction DB changes.
- The check remains streaming and does not increase archive memory usage.

### Verified
- Focused prediction archive, depth archive, and historical dataset tests pass.

## [2.20.142] — 2026-08-03

### Changed
- The depth recorder buffers aggregate trades until depth synchronization succeeds.
- The pre-synchronization buffer reserves capacity for the proving depth update.

### Fixed
- Aggregate trades arriving before the first contiguous depth update are retained.
- Buffer overflow now aborts without publishing a truncated archive.

### Security
- Unsynchronized or incomplete archives remain unpublished.
- The recorder still uses public data and receives no credentials.

### Verified
- Focused depth archive, market replay, and readiness tests pass.

## [2.20.141] — 2026-08-03

### Changed
- Replay readiness now permits one validation report for each archive hash.
- Duplicate reports use the smaller coverage value in diagnostic totals.

### Fixed
- Repeated validation files can no longer inflate validated real-order counts.
- Multiple reports for one archive now block replay readiness explicitly.

### Security
- Duplicate evidence fails closed before replay-model approval.
- The change cannot enable APPLY, remove HALT, or create an order.

### Verified
- Focused replay readiness and validation tests pass.

## [2.20.140] — 2026-08-03

### Changed
- Exact accounting now owns the recognized valued-commission status contract.
- Replay calibration uses the same commission provenance contract as reports.

### Fixed
- Legacy valued commissions no longer disappear from execution outcomes.
- Unknown commission statuses now fail closed even when a quote value exists.

### Security
- The change does not enable APPLY, remove HALT, or create an order.
- Unpriced and unknown provenance cannot enter calibrated fee totals.

### Verified
- Focused accounting, User Stream, revaluation, and dashboard tests pass.
- The release harness passes all checks with 1,170 total tests.

## [2.20.139] — 2026-08-02

### Changed
- Risk snapshots now identify symbols with incomplete FIFO loss-streak evidence.
- Runtime telemetry publishes loss-streak completeness as structured data.

### Fixed
- An imported FIFO boundary no longer makes all risk telemetry unavailable.
- Account reconciliation and SHADOW collection continue while BUY remains blocked.

### Security
- Unknown loss-streak provenance still blocks BUY without inventing a streak value.
- The change cannot remove HALT, enable APPLY, or create an order.

### Verified
- Focused risk, accounting, recovery, and architecture tests pass.

## [2.20.138] — 2026-08-02

### Changed
- The supervisor now publishes structured account reconciliation evidence.
- The dashboard displays authoritative evidence without parsing diagnostic text.

### Fixed
- Raspberry Pi verification no longer accepts a missing reconciliation result.
- Account and inventory differences now reach release verification directly.

### Security
- Missing, disabled, or malformed reconciliation evidence blocks Pi approval.
- Verification metrics expose mismatch counts without account quantities.

### Verified
- Eleven focused supervision and verification tests pass.
- The complete 971-test suite and Python compilation pass.

## [2.20.137] — 2026-08-02

### Changed
- GitHub pull request merge handling now requires exact workflow and event evidence.
- Release-continuity tests now have a focused component module.

### Fixed
- Local and octopus merges can no longer imitate a GitHub pull request merge.
- A version change in the pull request base parent cannot pass as the candidate change.

### Security
- The release gate accepts only the event's exact pull request head commit.
- Oversized, missing, malformed, or inconsistent event evidence fails closed.

### Verified
- The complete 964-test suite and Python compilation pass.
- Seven focused release-continuity tests pass.

## [2.20.136] — 2026-08-02

### Changed
- GitHub commands must derive the repository name from the configured `origin`.
- The release learning record documents the failed manual repository transcription.
- Risk loss streaks now use the canonical exact FIFO SELL allocation.
- Migration 010 rebuilds a bounded derived FIFO state from authoritative trades.

### Fixed
- The release workflow no longer permits a manually reconstructed GitHub repository name.
- Average-cost signs no longer disagree with FIFO PnL in the loss circuit breaker.
- Numeric migration fixtures no longer use a character range as a version limit.

### Security
- Missing FIFO coverage preserves accounting but blocks that symbol's risk streak.
- The derived index keeps 4,096 SELL outcomes and at most 65,536 open FIFO lots.

### Verified
- Both 2.20.135 GitHub workflows passed after the corrected read-only watch.
- The complete 960-test suite and the technical English check pass.

## [2.20.135] — 2026-08-02

### Changed
- Monthly HMM evaluation now uses one sequence for each symbol and horizon.
- Boosting and HMM scores retain one common eligible test cohort.

### Fixed
- Labels from different horizons no longer create false HMM transitions.
- HMM state no longer passes between horizons or symbols at one market time.

### Security
- A cold HMM sequence excludes the same row from both model scores.
- The change remains inside the offline SHADOW report and cannot authorize APPLY.

### Verified
- The complete 957-test suite and the technical English check pass.

## [2.20.134] — 2026-08-02

### Changed
- Challenger accuracy now uses one full-coverage cohort for every prediction source.
- Reports show resolved observations, common observations, and source availability.

### Fixed
- Intermittent predictor availability can no longer bias side-by-side accuracy.
- Large-DOWN capture now uses the same observations for every challenger.

### Security
- Outcomes after the report cutoff cannot affect sources, coverage, or scores.
- The report remains SHADOW evidence and cannot authorize APPLY.

### Verified
- The complete 954-test suite and the technical English check pass.

## [2.20.133] — 2026-08-02

### Changed
- Exact accounting now provides one canonical Decimal FIFO replay function.
- Dashboard trade summaries use a separate service built on that function.

### Fixed
- Valued `legacy` commissions no longer block realized FIFO PnL.
- A stored zero legacy commission no longer becomes an estimated fee.

### Security
- Unpriced commissions and incomplete FIFO history still block realized PnL.
- Trades after the report cutoff cannot enter current FIFO results.
- The dashboard remains read-only and does not change execution decisions.

### Verified
- The complete 951-test suite and the technical English check pass.

## [2.20.132] — 2026-08-02

### Changed
- OTOCO success and recovery now use one verified journal-state finalizer.
- A definitive OTOCO rejection now fails both prepared intents immediately.

### Fixed
- Lost OTOCO acknowledgements now mark a confirmed filled BUY as protected.
- Restart recovery no longer reports a false unprotected fill for that state.

### Security
- OTOCO reconciliation still requires one BUY and two valid SELL protection legs.
- Uncertain or structurally invalid reconciliation remains fail closed.

### Verified
- The complete 944-test suite and the technical English check pass.

## [2.20.131] — 2026-08-02

### Changed
- Re-anchor planning now normalizes desired BUY levels after market-gap adjustment.
- The planner preserves unique descending ranks before it matches open BUY orders.

### Security
- Defensive normalization prevents future level transformations from assigning duplicate desired ranks.
- Existing age, trigger, movement, market-crossing, and cycle limits remain unchanged.

### Verified
- The complete 942-test suite and the technical English check pass.

## [2.20.130] — 2026-08-02

### Changed
- Third-asset commission conversion now requires an exact one-minute candle timestamp.

### Fixed
- A missing conversion minute no longer uses the first later Binance candle.
- A mismatched candle cannot enter the process conversion cache.

### Security
- Commission valuation fails closed as `unpriced` when no exact conversion minute exists.
- Historical and LIVE accounting cannot use future candle prices for commission provenance.

### Verified
- The complete 941-test suite and the technical English check pass.

## [2.20.129] — 2026-08-02

### Changed
- Breakeven maintenance now owns a separate protection service.
- A canceled OCO must become absent before its replacement starts.

### Fixed
- A successful cancel response no longer bypasses old OCO verification.
- An empty, malformed, or failed replacement now creates a persistent HALT.

### Security
- Replacement errors expose only bounded error types in HALT metadata and logs.
- Breakeven maintenance cannot continue mutations after protection becomes uncertain.

### Verified
- The complete 939-test suite and the technical English check pass.
- Semgrep, replay, walk-forward, recovery, migration, and deployment checks pass.

## [2.20.128] — 2026-08-02

### Changed
- Exchange step arithmetic now requires finite positive step and tick values.
- Order normalization now validates all four required exact symbol filters together.
- Market filter reads validate required fields before the result enters the process cache.

### Fixed
- A zero exchange step no longer bypasses rounding or selects the eight-decimal fallback.
- Missing price, quantity, or minimum-notional filters now cause a local fail-closed error.

### Security
- Invalid exchange filter metadata cannot reach an order submission boundary.

### Verified
- The complete 935-test suite and the technical English check pass.

## [2.20.127] — 2026-08-02

### Changed
- Public market reads now apply a process-local cooldown from Binance `Retry-After` evidence.
- HTTP 418 uses a 120-second default when Binance omits a valid cooldown.
- HTTP 429 uses a one-second default when Binance omits a valid cooldown.

### Fixed
- HTTP 418 and 429 no longer cause three immediate read retries.
- The unused float-based USDT balance helper was removed.

### Security
- Cooldown errors retain only the status, endpoint path, and bounded delay.
- Signed query values cannot enter cooldown diagnostics.

### Verified
- The complete project test suite and the technical English check pass.

## [2.20.126] — 2026-08-02

### Added
- VWAP discount generation now reacts to regime, ATR, and exact PnL evidence.
- New bounded discount multipliers permit reviewed operator configuration.

### Changed
- VWAP discount EMA state now stores exact decimal text between generator runs.
- The VWAP update command uses its active Python interpreter.

### Fixed
- Discount bounds, smoothing, and state persistence now govern a value that can change.
- The unused duplicate FIFO calculation was removed from the autotune command.

### Security
- Invalid or non-finite discount inputs fail before configuration output.
- DOWN, loss, and volatility evidence can only require a deeper discount with default settings.

### Verified
- The complete project suite and focused VWAP, exception, architecture, deployment, and numeric tests pass.

## [2.20.125] — 2026-08-02

### Added
- SHADOW now compares 15 version-two candidates on each shared market snapshot.
- The new matrix tests 1.00% to 1.10% TP, 3-to-8-minute TTL, and 5-to-10 basis-point BUY distances.
- One combined candidate uses a bounded dynamic BUY distance from spread and ATR evidence.
- The dashboard shows independent samples, outcomes, backlog, fill rate, confidence intervals, regimes, and Holm status.

### Changed
- New candidate semantics use new experiment identifiers. Historical rows remain unchanged.
- User Stream telemetry separates planned idle refreshes from transport failures and legacy reconnect evidence.

### Security
- All candidates remain SHADOW-only and cannot change orders, HALT, APPLY, CAP, or Risk Manager output.
- Future prediction horizons remain normal pending work. Only overdue outcomes appear as backlog.

### Verified
- The complete project test suite and focused prediction, stream, dashboard, security, and architecture tests pass.

## [2.20.124] — 2026-08-01

### Fixed
- Operator commands now resolve existing persistent Pi control paths without systemd environment injection.
- The Mainnet User Stream drill now proves the same HALT file used by `mybot.service`.

### Security
- Explicit Testnet and temporary control paths remain unchanged.

### Verified
- Tests cover persistent path resolution, explicit path isolation, and drill preflight behavior.

## [2.20.123] — 2026-08-01

### Added
- SHADOW now records three combined RANGE, five-minute, maker-only candidates.
- A bounded Mainnet drill proves account-event to REST reconciliation under persistent HALT.

### Fixed
- The Pi guide now uses the persistent User Data Stream evidence path.

### Security
- The Mainnet drill uses intent-first journaling, a 10 USDT hard limit, immediate cancellation, and mandatory cleanup.
- The drill cannot remove HALT, enable APPLY, or run with another open `SOLUSDT` order.

### Verified
- Tests cover equal-snapshot candidates, RANGE gating, zero-fill cancellation, cleanup, and persistent evidence paths.

## [2.20.122] — 2026-08-01

### Fixed
- Walk-forward approval now excludes samples without sufficient prior training history.
- AI readiness now uses a deterministic bootstrap confidence interval.

### Changed
- AI APPLY requires 60 real closed decisions by default.

### Verified
- Tests cover cold-start exclusion, small-sample rejection, and deterministic confidence intervals.

## [2.20.121] — 2026-08-01

### Fixed
- The Russian dashboard now translates dynamic operational summaries and common runtime states.
- Known risk reasons now use localized text without changing unknown evidence.

### Verified
- The complete project suite and Technical English check pass.

## [2.20.120] — 2026-08-01

### Added
- Historical attribution gaps now use a durable reviewed lifecycle.
- A guarded command verifies exact journal evidence before review.

### Changed
- Only pending attribution gaps block AI readiness and Pi verification.
- Reviewed and linked rows remain in the authoritative evidence table.

### Security
- Review requires an exact count, cutoff, approved reason, and matching Mainnet journal orders.
- Review never creates a `decision_id`, RAG document, fill attribution, or exchange mutation.

### Verified
- The complete project suite and Technical English check pass.

## [2.20.119] — 2026-08-01

### Fixed
- Risk alerts now ignore volatile retry counters when they deduplicate one unchanged failure.

### Verified
- Risk alert tests prove repeated causes stay quiet and changed causes alert immediately.

## [2.20.118] — 2026-08-01

### Security
- Semgrep processes now receive a minimal environment without application credentials.

### Verified
- Semgrep policy, rule fixtures, environment isolation, and harness profile tests pass.

## [2.20.117] — 2026-08-01

### Fixed
- Runtime authentication rejection now refreshes two-source IP Guard evidence.
- DRY and Testnet ignore pending LIVE public-IP changes.
- Position-limit maps now reject malformed, duplicate, and unconfigured items.

### Security
- Invalid financial map items cannot silently remove a position limit.
- IP Guard continues to persist fingerprints only, without public addresses.

### Verified
- IP Guard, configuration, authentication, architecture, numeric, and exception tests pass.

## [2.20.116] — 2026-08-01

### Added
- Local Semgrep rules detect unsafe Python execution and error patterns.
- Positive and negative fixtures verify every project rule.

### Changed
- Local and release verification now run a pinned offline Semgrep scan.
- Semgrep uses a separate hashed environment and never runs on Raspberry Pi.

### Verified
- Rule fixtures, production scanning, harness integration, CI contracts,
  deployment assets, and architecture tests pass.

## [2.20.115] — 2026-08-01

### Fixed
- Runtime telemetry clears the changed-IP flag after automatic acceptance.
- Dashboard status now matches the accepted persistent IP Guard state.

### Verified
- Automatic acceptance, telemetry recovery, architecture, documentation, and
  project tests pass.

## [2.20.114] — 2026-08-01

### Changed
- IP Guard now verifies changed public IP fingerprints automatically.
- Two independent HTTPS sources must agree before the verification starts.
- The complete signed read-only Binance preflight must pass before acceptance.

### Security
- Failed authentication keeps the pending fingerprint blocked.
- Automatic IP acceptance never removes HALT or changes trading limits.
- Persisted state contains fingerprints only. It never contains the public IP.

### Verified
- Pending-state, authentication retry, automatic acceptance, source-consensus,
  secret-exposure, preflight, and architecture tests pass.

## [2.20.113] — 2026-08-01

### Added
- SQLite migration 009 creates a bounded derived index for exact SELL results.
- One shared process lock serializes circuit HALT and risk-state changes.

### Changed
- Risk checks read only the SELL outcomes required by the configured loss limit.
- Dashboard and Telegram IP-block notices now contain only the cause and action.

### Fixed
- Concurrent evaluate, HALT, cooldown, synchronization, and reset operations no
  longer overwrite newer control state.
- The risk cycle no longer replays all trade history every 15 seconds.

### Verified
- Control-lock concurrency, migration backfill, bounded growth, priced fee retry,
  dashboard notices, risk regression, and project tests pass.

## [2.20.112] — 2026-08-01

### Added
- The dashboard shows a verified update notice when the current heartbeat is
  `IP_BLOCKED`.
- The Raspberry updater sends an English Telegram notice after dashboard and
  SQLite readiness checks pass.

### Security
- The notice does not contain the public IP, credentials, balances, or signed
  request data.
- The updater writes one bounded derived status record and replaces it after
  each verified deployment.

### Verified
- Deployment status validation, dashboard notice isolation, Telegram message,
  service sandbox, updater ordering, documentation, and project tests pass.

## [2.20.111] — 2026-08-01

### Fixed
- One failed dashboard section no longer prevents healthy sections from updating.
- Dashboard SQLite readers can create required WAL coordination sidecars.
- The browser stops API polling for the server-provided interval after HTTP 429.
- The dashboard uses only canonical trade summary and fill endpoints.

### Changed
- The authenticated per-client API limit is now 360 requests per minute.

### Verified
- Dashboard isolation, rate-limit recovery, SQLite sandbox, deployment asset,
  documentation, and complete project tests pass.

## [2.20.110] — 2026-08-01

### Fixed
- Partially filled BUY orders now add only their unfilled quantity to portfolio,
  symbol, correlated, and remaining-budget exposure.
- Reconciliation tolerance now uses the unambiguous `_FRACTION` name, a 0.1%
  default, and a strict 0-to-5% range.
- Missing Value at Risk history now creates a configuration block. It does not
  increment API failures or start an API cooldown.

### Changed
- The legacy `RISK_RECONCILE_TOLERANCE_PCT` name remains a deprecated fallback.
  The new variable takes priority when both names exist.
- The Raspberry updater migrates only the previous 2% default. It blocks before
  service shutdown when it finds a custom legacy value.

### Verified
- Partial-fill exposure, invalid quantity, tolerance migration, configuration
  classification, risk regression, and complete project tests pass.

## [2.20.109] — 2026-08-01

### Fixed
- BUY placement now reads the mutable worker stop flag before each exchange
  boundary instead of keeping one stale Boolean value.
- Worker shutdown logs now distinguish `SIGINT` from `SIGTERM`.
- Stable standard-library and HTTP dependencies are imported directly by the
  BUY service instead of entering the runtime dependency map.

### Verified
- Live stop-state checks, signal diagnostics, architecture budgets,
  documentation, and complete project tests pass.

## [2.20.108] — 2026-08-01

### Added
- A daily database-retention service archives terminal SHADOW predictions
  before it removes them from the active database.
- The retention report classifies accounting and recovery databases as
  authoritative data with no automatic deletion.

### Fixed
- Opening the AI database no longer deletes old decisions as a hidden side
  effect.

### Security
- Retention requires a recent successful encrypted backup, a mode-0600
  content-addressed archive, terminal outcomes, and a bounded transaction.
- Pending predictions, fills, FIFO lots, unresolved records, order intents,
  and lifecycle evidence are never automatically deleted.

### Verified
- Retention archive, stale-backup block, pending-row preservation, deployment
  assets, documentation, and complete project tests pass.

## [2.20.107] — 2026-08-01

### Fixed
- Startup recovery now classifies missing orders from exact Binance error codes
  across wrapped exception chains.
- Definitive journal, exchange, symbol, response, and quantity conflicts now
  create a durable HALT before startup stops.
- A damaged halt marker is archived before a new marker replaces it.

### Changed
- The Raspberry Pi runbook now explains recovery for an intent whose symbol is
  absent from the current configuration.

### Verified
- Missing-order classification, wrapped errors, durable HALT, damaged evidence,
  startup recovery, documentation, and complete project tests pass.

## [2.20.106] — 2026-08-01

### Fixed
- The Testnet drill now uses a `LIMIT_MAKER` BUY one percent below the current
  price instead of a LIMIT BUY fifty percent below it.
- The bounded order stays near the reference price and cannot execute as a
  taker.

### Verified
- Maker-only parameters, filter-compatible price distance, Testnet cleanup,
  and complete project tests pass.

## [2.20.105] — 2026-08-01

### Security
- Testnet HTTP and network errors now contain only the status, Binance code,
  exception class, and endpoint path.
- Signed URLs, query parameters, and request signatures cannot enter a
  traceback from the Testnet client.
- Testnet response JSON now has a strict 64 KiB decoded-byte limit.

### Verified
- Signed-error redaction, bounded response, Testnet smoke, documentation, and
  complete project tests pass.

## [2.20.104] — 2026-08-01

### Added
- Added a confirmed Testnet User Data Stream drill.
- The drill forces one socket reconnect, creates one bounded non-filling LIMIT
  order, receives its authenticated event, and confirms it with REST.
- The Testnet verification profile exposes the drill as a separate required
  check when mutation confirmation is present.

### Security
- The drill accepts only the Binance Spot Testnet host.
- It requires `BOT_TESTNET_ORDER_CONFIRMED=YES`, enforces the existing notional
  ceiling, and cancels the Testnet order in `finally`.
- A stream event remains notification-only and cannot authorize an order.

### Verified
- Controlled-reconnect, event-to-REST, cleanup, confirmation, stream-safety,
  Testnet-smoke, and complete project tests pass.

## [2.20.103] — 2026-08-01

### Changed
- The SHADOW contour now records 11 one-factor candidates on each shared
  snapshot.
- The candidates test RANGE-only entry, TP targets of 1.15%, 1.30%, and 1.50%,
  and maker-only entry plus TP.
- The candidates also test BUY lifetimes of 5, 10, and 15 minutes and BUY
  distances of 10, 15, and 20 basis points.
- Re-anchor is excluded from the promotion candidate set.

### Security
- Every candidate retains the untouched baseline and remains
  `apply_allowed=false`. The change does not enable APPLY, change CAP, clear
  HALT, or add order capability.

### Verified
- Same-snapshot, fee-floor, no-look-ahead, maker-policy, TTL, BUY-distance,
  re-anchor-exclusion, and complete project tests pass.

## [2.20.102] — 2026-08-01

### Fixed
- LIVE now publishes a fail-closed `RISK_PENDING` heartbeat before slow
  authenticated preflight and market initialization.
- The Raspberry Pi updater accepts a fresh `RISK_PENDING` heartbeat as ready.
  It still rejects `INTENTIONALLY_STOPPED`.

### Security
- The early heartbeat blocks BUY and preserves a persistent HALT state.
  It does not enable APPLY, change CAP, or mutate Binance.

### Verified
- Startup-order, initial-risk, deployment-readiness, and complete project tests
  pass. The release harness records the final counts before publication.

## [2.20.101] — 2026-07-31

### Fixed
- Star History now refreshes after each new GitHub star and reconciles hourly.
  This replaces the stale daily-only update window.

### Changed
- Rewrote the README and current technical guides with the project
  ASD-STE100 Simplified Technical English profile.
- Synchronized current commands, configuration defaults, systemd units,
  implemented features, approval boundaries, and known limits with the code.
- Added separate implementation-status, configuration, and command references.
- Replaced obsolete backtest options with the current positional CSV and
  `--archive` command forms.
- Simplified long historical log sentences without a change to dates, versions,
  decisions, root causes, or test evidence.
- Added one controlled vocabulary, procedure format, and documentation scope.

### Added
- Added an objective documentation check for sentence limits, contractions,
  missing documents, Markdown exclusions, and required project guides.
- Added contributor and agent rules that require the writing profile and its
  documentation check.

### Verified
- The Technical English check and nine focused documentation regressions pass.
- Compileall and the complete project suite pass (818 tests).

## [2.20.100] — 2026-07-31

### Fixed
- Consecutive AI-provider failures now use bounded exponential negative-cache
  backoff instead of retrying at the same short interval throughout an outage.
- Provider diagnostics expose only the exception class and validated HTTP
  status; endpoint URLs and response text no longer enter operator logs.

### Changed
- Identical low-confidence and provider-error messages are rate-limited to one
  per hour. Decision and usage evidence is still recorded for every provider
  response, so SHADOW statistics remain complete.

### Security
- The LLM remains advisory and fail-safe. Provider failures still select the
  deterministic strategy and cannot change HALT, CAP or order authority.

### Verified
- Backoff, recovery, log-sanitization, diagnostic-rate and usage-preservation
  regressions pass; compileall and the complete suite pass (809 tests).

## [2.20.99] — 2026-07-31

### Added
- The dashboard chart grid now includes exact rolling 24-hour trading volume
  in USDT next to memory, using both executed BUY and SELL quote turnover.

### Security
- Financial aggregation uses `Decimal`, excludes future fills at every chart
  timestamp, and degrades only the volume series when exact trade data is
  unavailable. It does not change trading, HALT, SHADOW or order authority.

### Verified
- Exact-window, no-look-ahead, localization and responsive chart wiring
  regressions pass; complete verification is recorded before publication.

## [2.20.98] — 2026-07-29

### Fixed
- Production soak now blocks on `INSUFFICIENT_HISTORY` outcomes created during
  the current audited runtime window instead of rescanning lifetime expirations
  as if they were failures of every later clean run.

### Changed
- Prediction evidence reports current-soak expirations and lifetime expiration
  totals separately. Historical rows remain immutable and excluded from
  fabricated backfill when verified archives do not cover their minute window.

### Security
- Missing expiry timestamps fail closed. The patch changes reporting scope only
  and does not alter HALT, SHADOW, CAP, RAG eligibility or order authority.

### Verified
- Current-window, historical-expiration, future-pending and overdue regressions
  pass; compileall and the complete suite pass (803 tests). Release
  verification is recorded in the signed release manifest.

## [2.20.97] — 2026-07-29

### Fixed
- Production soak no longer treats normal unresolved 1/5/15-minute SHADOW
  horizons as a prediction backlog. Only outcomes overdue beyond a bounded
  settlement grace period or unrecovered `INSUFFICIENT_HISTORY` outcomes block
  approval.
- Missing or legacy prediction schema cannot silently satisfy the backlog gate;
  the report now exposes whether backlog evidence is verifiable.

### Added
- Soak evidence separates future pending, settlement-grace, overdue and expired
  outcome counts, with a configurable five-minute settlement delay ceiling.

### Security
- The correction changes reporting only. HALT, SHADOW, CAP and order mutation
  authority remain unchanged.

### Verified
- Pending-horizon and fail-closed overdue/expired regressions pass; complete
  compileall and the complete suite pass (803 tests). Release verification
  results are recorded in the signed release manifest.

## [2.20.96] — 2026-07-29

### Added
- A SHADOW-only experiment contour records five fee-floor-safe strategy
  candidates against the untouched current plan on identical snapshots:
  TP floor, 15 bps BUY gap, five-minute TTL, bounded re-anchor and
  DOWN/PANIC veto.
- Runtime evidence reports each candidate's independent samples, expectancy,
  baseline edge, fill rate, drawdown, regime coverage and promotion reasons.

### Changed
- Statistical approval and walk-forward logic now live in their technical
  modules instead of the guarded prediction runtime coordinator.
- Candidate sets are recorded at most every five minutes and expensive reports
  refresh at most every 15 minutes.

### Security
- Experiment kinds require an explicit immutable baseline and have no exchange
  or order transport. `apply_allowed` remains false even for an eligible report.
- Promotion requires candidate-specific configuration p-values with Holm
  correction in addition to the existing horizon/regime Holm gate.

### Verified
- Focused prediction, experiment, supervisor recovery and architecture
  regressions pass, including no-look-ahead, TTL, regime veto, bounded cadence,
  explicit baseline and no-order-capability checks; compileall and the complete
  suite pass (801 tests).

## [2.20.95] — 2026-07-29

### Fixed
- Every SQLite migration now executes its complete schema change and
  `schema_migrations` record inside one `BEGIN IMMEDIATE` transaction. A power
  loss or SQL failure rolls back both instead of leaving a partially applied,
  unrecorded migration.
- Migration scripts are parsed with SQLite's statement parser, preserving
  trigger bodies without the implicit commits caused by `executescript`.
- Duplicate numeric migration versions are rejected before the database is
  created or modified.
- A partially applied legacy `ADD COLUMN` migration can resume only when the
  existing column has the exact expected type, nullability and default;
  mismatched schema evidence fails closed.
- Fresh-database exact-accounting bootstrap and its completion marker now share
  one caller-owned transaction.

### Verified
- Focused migration, exact-accounting, compatibility and SQLite safety
  regressions pass (16 tests), including injected mid-migration, version-record
  and bootstrap failures; compileall and the complete suite pass (791 tests).

## [2.20.94] — 2026-07-29

### Fixed
- The supervisor now translates its first `SIGTERM` into the existing graceful
  `KeyboardInterrupt` shutdown path, publishes `STOPPING`, stops workers and
  releases the singleton lock.
- `mybot.service` now uses `KillMode=control-group`, so workers receive TERM
  during service shutdown instead of remaining unsupervised until SIGKILL.
- Non-zero worker exits are tracked in a rolling one-hour window. The third
  exit activates bounded exponential backoff regardless of individual runtime,
  and the fifth emits one sanitized Telegram restart-storm alert.
- Successful intentional child shutdown clears its restart-window history;
  failed cleanup retains the process and its evidence for another attempt.

### Changed
- The service declares an explicit five-start-per-hour systemd limit as a
  second boundary around supervisor-level restart handling.

### Verified
- Focused SIGTERM, slow-crash window, alert, expiry, child cleanup and systemd
  regressions pass; compileall and the complete suite pass (785 tests).

## [2.20.93] — 2026-07-29

### Fixed
- The daily Telegram digest now displays exact fees as a negative account
  impact instead of applying the generic positive-value prefix. Stored
  commission values and net FIFO PnL accounting are unchanged.

### Verified
- The digest regression proves a `0.055 USDT` commission is displayed as
  `Fees: -0.06 USDT` and rejects any positive fee prefix; compileall and the
  complete suite pass (782 tests).

## [2.20.92] — 2026-07-29

### Security
- Watchdog Telegram delivery now passes the bot token, chat ID and message body
  through file descriptors instead of process arguments.
- An inactive bot is restarted only while its systemd unit remains explicitly
  enabled; an inactive disabled or masked unit is treated as an intentional
  operator stop.

### Fixed
- Offline Telegram notifications now expire after 24 hours and the durable
  outbox is capped at 288 files, preventing stale notification floods and
  unbounded storage growth after a prolonged outage.
- Missing default-route evidence is reported directly without probing a
  hard-coded private gateway.
- The Raspberry Pi runbook now defines `disable --now` as the persistent
  operator-stop contract and documents the explicit resume command.

### Verified
- Focused watchdog regressions cover intentional-stop suppression, secret-free
  curl arguments, outbox TTL/CAP retention and missing-route behavior; shell
  syntax, compileall and the complete suite pass (782 tests).

## [2.20.91] — 2026-07-29

### Fixed
- L2 replay maker matching now fills a better resting local limit when an
  aggressive public trade passes through its price, while retaining the local
  maker price and conserving the event's shared quantity.
- Cancel requests now take effect only after the configured venue latency, so
  an order can still receive a fill while its cancellation is in flight.
- Public FIFO depth is handed between same-price local orders as shared state
  rather than added twice.
- Replay request throttling now rejects submit or cancel without mutating
  replay state instead of aborting the complete simulation.

### Verified
- Focused maker price-through, non-crossing, cancel-latency, shared-queue and
  rate-limit regressions pass together with archive, validation and readiness
  replay tests; compileall and the complete suite pass (778 tests).

## [2.20.90] — 2026-07-29

### Fixed
- Raspberry Pi update recovery now records the previous commit before
  fast-forward and reinstalls that checkout's hashed dependency lock before
  restoring LIVE services. If rollback is unproven or external deployment
  assets may be partial, `mybot` and its watchdog remain stopped while the
  dashboard is started for diagnosis.
- Environment-file rewrites are now atomic literal line replacements, so
  operator paths containing sed replacement characters cannot corrupt `.env`.
- Dashboard readiness fails immediately on a malformed authentication token
  instead of timing out as HTTP `000`.
- Post-update heartbeat readiness no longer accepts
  `INTENTIONALLY_STOPPED` after an expected service start.
- The runbook documents that a break-glass authorization is consumed by the
  attempt and must be recreated for any retry.

### Verified
- Deployment recovery regressions cover rollback ordering, partial-asset
  blocking, literal special-character paths, malformed-token diagnostics,
  heartbeat state and break-glass documentation; shell syntax, compileall and
  the complete suite pass (772 tests).

## [2.20.89] — 2026-07-29

### Fixed
- The blocked-SHADOW log-rate regression now declares its required per-order
  CAP instead of inheriting an operator environment value. The same assertions
  therefore exercise inventory-skew diagnostics on clean Linux CI, developer
  machines and isolated archives.

### Verified
- The previously Linux-only failed node is reproduced from the safe harness
  diagnostic and passes with an empty `BOT_CAP_PER_ORDER` parent environment;
  compileall and the complete suite pass (767 tests).

## [2.20.88] — 2026-07-29

### Fixed
- The verification harness now reports only allowlisted failed pytest node IDs.
  It excludes tracebacks, assertion values, request bodies, and other child output.
  Thus, Linux-only CI failures remain actionable without weaker secret containment.

### Verified
- The allowlist regression proves the failed node ID is retained while a
  synthetic signed URL is absent from the report; compileall and the complete
  suite pass locally (767 tests).

## [2.20.87] — 2026-07-29

### Fixed
- A fail-closed SHADOW cycle still computes and persists fresh evidence every
  minute, but unchanged PLAN, ATR, regime, expectancy, inventory and position
  diagnostics are now emitted at most once per 15 minutes. Safety errors,
  recovery changes and risk alerts remain immediate.
- Mainnet/Testnet lifecycle cleanup no longer replaces an already active
  primary failure. The report keeps the original error and records cleanup
  failures separately while HALT remains fail-closed.
- A formally FILLED BUY with zero executed quantity now fails with an explicit
  diagnostic before any price or slippage division.
- Canary evidence and Testnet mode names now say `journal_reload` instead of
  claiming process restart coverage. Operator documentation explicitly forbids
  removing a production OCO merely to satisfy canary preflight.

### Verified
- Blocked-SHADOW regression proves two consecutive observations persist twice,
  enter no mutation path and emit each routine diagnostic only once;
  canary regressions prove primary-error preservation, separate cleanup
  evidence, zero-execution blocking and secret-free reports. Compileall passes
  and the complete suite passes (766 tests).

## [2.20.86] — 2026-07-29

### Fixed
- The Pi updater now verifies and executes the updater from the requested
  signed target commit before backup or service mutation, so deployment steps
  introduced by a release apply on the first invocation.
- The target runner is extracted from the verified Git object and remains
  immutable while the checkout fast-forwards. Unsigned break-glass continues
  on the already installed runner and never executes unverified target code.

### Verified
- Target-runner signature/order, break-glass separation, persistent-control,
  service-state and stream-deployment regressions pass (4 focused tests);
  compileall and shell syntax checks pass; the complete suite passes (764
  tests).

## [2.20.85] — 2026-07-29

### Added
- A dedicated read-only User Data Stream shadow service now collects
  authenticated connection, reconnect and event-to-GET reconciliation evidence
  independently from execution workers.
- Sanitized stream-soak state persists below
  `/var/lib/ladder-dragon/user-stream`; dashboard and Pi verification consume
  the same path and require the observer service to be active.

### Fixed
- A persistent execution HALT no longer prevents the required 24-hour stream
  soak from starting. The observer contains no order placement, cancellation
  or replacement path and cannot relax Risk Manager.

### Verified
- User-stream parsing, deduplication, GET-only reconciliation, persistent
  service, dashboard, harness and deployment regressions pass (109 focused
  tests); compileall and shell syntax checks pass; the complete suite passes
  (763 tests).

## [2.20.84] — 2026-07-29

### Fixed
- Authoritative circuit HALT, risk state and alert evidence now live in the
  persistent systemd state directory instead of the volatile service runtime
  directory, with conflict-detecting pre-stop migration for existing Pi
  installations.
- LIVE supervisor telemetry starts as `RISK_PENDING` with BUY blocked until the
  first authenticated risk snapshot completes, so a slow startup can no longer
  briefly report an unsafe false `RUNNING` state.
- Dashboard and Pi verification read the same persistent risk-state path while
  explicit custom and isolated Testnet control paths remain unchanged.

### Verified
- Persistent-path, explicit-path, startup risk-gate, deployment-order and
  service-contract regressions pass (74 focused tests); compileall and shell
  syntax checks pass; the complete suite passes (759 tests).

## [2.20.83] — 2026-07-29

### Fixed
- The daily digest systemd sandbox now permits SQLite WAL shared-memory
  coordination while the report connection remains `mode=ro`, preventing
  `unable to open database file` at the scheduled 08:00 run.
- Telegram delivery accepts only the known alert variables already injected by
  systemd, so a closed configuration-directory parent no longer suppresses the
  digest or its figure-free `BLOCKED` warning.
- Missing databases now use the same deduplicated warning path, and failed
  oneshot runs receive two bounded five-minute retries without duplicate
  successful reports.

### Verified
- Daily digest, Telegram configuration, systemd isolation, retry,
  idempotency, deployment and documentation regressions pass (98 focused
  tests); compileall and the complete suite pass (753 tests).

## [2.20.82] — 2026-07-29

### Changed
- Dashboard positions/protection and AI/data-quality cards now share one
  balanced two-column row on desktop and collapse to one column on narrow
  screens.
- Dashboard body, diagnostics, tables, controls and operational values use one
  13 px baseline; section headings and primary values retain a clear larger
  hierarchy.

### Verified
- Dashboard layout, responsive behavior, typography, localization, and asset regressions pass (120 focused tests).
  The measured 1440 px and 390 px layouts have no horizontal overflow.
  Compileall, JavaScript syntax, and the complete suite pass (751 tests).

## [2.20.81] — 2026-07-29

### Fixed
- Manual and recovery execution halts now atomically mirror their authoritative
  marker into persistent risk state, so dashboard and Pi verification cannot
  report `risk_state.json` as unavailable while BUY is already blocked.

### Verified
- Manual-halt creation, existing-equity preservation and risk regressions pass
  (53 focused tests); compileall and the complete suite pass (750 tests).

## [2.20.80] — 2026-07-29

### Changed
- SHADOW AI provider refresh is non-blocking and deduplicated per symbol:
  deterministic execution consumes only a fresh cached recommendation, while
  APPLY retains its synchronous approval semantics.
- User-stream fill reconciliation and protection now run before commission
  valuation and append-only latency telemetry.
- Protection reuses one authoritative balance snapshot for both exact
  cost-basis coverage and sellable quantity instead of issuing a duplicate
  signed account request.
- Real-time aggregate trade flow maintains an exact rolling total, making
  immutable market snapshots constant-time as the in-memory window grows.
- The dashboard position card is reduced to one operational summary: protection
  required/confirmed, managed protected and unprotected quantities, BUY block,
  total balance, legacy balance and the exact reason cost basis is hidden.
- User-stream monitoring now shows only connection state and execution impact
  in the primary view; non-zero counters and sanitized errors are available in
  a conditional diagnostics disclosure instead of one dense status sentence.

### Verified
- SHADOW, protection, trade-flow, OCO, STOP, gap, and safety regressions pass (159 focused tests).
  Dashboard, localization, API security, and deployment regressions pass (125 focused tests).
  JavaScript syntax, compileall, and the complete suite pass (748 tests).

## [2.20.79] — 2026-07-29

### Fixed
- Expanding walk-forward splits now use binary label cutoffs and immutable
  training-prefix views instead of rescanning and copying the entire dataset
  for every test sample.
- The defensive ensemble treats `FLAT` and `UP` as compatible safe votes,
  retains confident `DOWN`/`PANIC` vetoes and reduces baseline CAP by half for
  weak danger evidence instead of disabling range trading.
- Open-interest change now requires two distinct timestamped observations, so
  a sparse series cannot compare one stale point with itself.
- Realized-volatility features now use population standard deviation and no
  longer count constant directional drift as volatility.

### Verified
- Prediction pipeline, no-look-ahead, risk non-expansion, OI provenance,
  volatility semantics, version and documentation regressions pass (63
  focused tests); compileall and the complete suite pass (743 tests).

## [2.20.78] — 2026-07-29

### Fixed
- The verification harness now re-executes through the repository `.venv`
  before importing project dependencies when a local virtual environment
  exists, so an accidental host-`python3` invocation cannot fail on missing
  project packages.
- CI and other explicitly provisioned environments without a repository
  `.venv` continue using their selected interpreter, while a failed or looping
  local re-exec blocks with a clear diagnostic.

### Verified
- Host-Python re-exec, missing-venv CI fallback, loop prevention, harness,
  version and deployment regressions pass (81 focused tests); compileall and
  the complete suite pass (740 tests).

## [2.20.77] — 2026-07-29

### Added
- Quote-currency decision value now compares a defensive regime gate with the
  exact always-trade counterfactual, including movement-weighted confusion and
  large-DOWN capture.
- Source-hashed historical Binance backfill creates multi-symbol 1/5/15-minute
  samples with strict feature/label cutoffs and optional timestamped trade
  imbalance, funding-rate and open-interest evidence.
- Extended SHADOW features, Platt calibration, shallow gradient boosting, a
  three-state HMM, a defensive-only ensemble and a monthly walk-forward report
  are available without adding order capabilities.
- An optional monthly systemd timer produces a hash-bound SHADOW artifact and
  sends Telegram only when its compact status changes.

### Changed
- The existing logistic challenger now reserves its latest chronological
  history for confidence calibration instead of treating raw softmax
  confidence as calibrated probability.
- Deep book and aggregate-trade collection continues through the existing
  public 1,000-level snapshot plus `depth@100ms`/`aggTrade` archive.

### Verified
- Defensive-value, no-look-ahead, feature, model, ensemble, monthly contour,
  deployment, prediction, archive and architecture regressions pass (96
  focused tests); compileall and the complete suite pass (737 tests).

## [2.20.76] — 2026-07-29

### Fixed
- `apply_cost_basis_plan` now requires and invokes a live revalidation callback
  before opening its write transaction, so a self-consistent but stale preview
  cannot supersede inventory lots through a non-CLI caller.
- Cost-basis apply compares the plan cursor with persisted statistics trades,
  emits a sanitized warning for any skipped range, and stores the exact range
  in migration `008` audit columns.
- A missing base-asset balance now fails immediately with an exact diagnostic
  instead of being represented as a plausible zero balance.

### Verified
- Cost-basis freshness, cursor audit, missing-asset and migration regressions
  pass; compileall and the complete suite pass (727 tests).

## [2.20.75] — 2026-07-29

### Fixed
- Dashboard AI diagnostics now expose the exact sanitized fail-closed runtime
  state, such as `runtime:recovery_blocked`, instead of collapsing every
  intentional protection block into the ambiguous `runtime_unhealthy`.
- A blocked SHADOW collector no longer writes all ladder prices on every
  observation. It emits a compact plan summary at most once per 15 minutes
  while continuing prediction and counterfactual evidence collection.

### Verified
- Dashboard runtime-state and blocked-SHADOW regressions pass; compileall and
  the complete suite pass (724 tests).

## [2.20.74] — 2026-07-29

### Changed
- GitHub now keeps `main` as its only remote branch: merged-branch cleanup is
  automatic, an active repository ruleset blocks creation of other branches,
  and the agent policy plus regression test preserve that workflow.
- RAG retrieval now combines directional cosine agreement with normalized
  feature distance, so proportional vectors with materially different market
  intensity no longer receive an identical score.
- Knowledge documents and retrieval links use 365-day retention, while each
  Python scoring pass is bounded to the newest 1,000 eligible candidates.
- AI prompt serialization sends each numeric context field once, preferring
  its exact text representation without duplicate float/text keys.
- Provider failures use a 30-second negative cache; successful and
  low-confidence responses retain the normal configured cache interval.
- The default hybrid RAG similarity threshold is raised from 0.65 to 0.75.

### Verified
- Hybrid similarity, retention, candidate bounds, compact prompt, negative
  cache, configuration and documentation regressions pass; compileall and the
  complete suite pass (722 tests), and the release harness passes all 904
  aggregated checks.

## [2.20.73] — 2026-07-29

### Fixed
- A startup recovery block now continues read-only SHADOW decisions and
  prediction evidence instead of leaving Decision DB stale indefinitely.
- Advisory observations can no longer overwrite `RECOVERY_BLOCKED` or another
  fail-closed heartbeat state with a misleading `RUNNING` state.
- Planning arguments and the process singleton are established before the
  recovery retry loop, so blocked SHADOW uses normalized inputs and cannot run
  concurrently in a second supervisor.

### Verified
- Recovery, SHADOW non-mutation, supervisor lifecycle and architecture
  regressions pass; compileall and the complete suite pass (717 tests).

## [2.20.72] — 2026-07-28

### Changed
- The 788-line worker coordinator is split into explicit lifecycle and
  non-buying event-loop services; the executable bootstrap is now 18 lines.
- `WorkerLoopContext` carries tracked orders and protection state explicitly
  while retaining the live `WorkerRuntimeState` view required by SIGTERM,
  WebSocket replacement and SQLite rebinding.
- Worker cleanup now attempts every transport, observer and symbol-lock
  release even when an earlier cleanup callback fails.
- Architecture and deployment contracts point to the new physical owners and
  prohibit BUY placement from the event-loop service.
- Release workflow learning now explicitly prohibits manually expanding an
  abbreviated SHA after a branch switch.

### Verified
- Lifecycle cleanup, live mutable state, worker safety, recovery, deployment
  and architecture regressions pass; compileall and the complete suite pass
  (714 tests).

## [2.20.71] — 2026-07-28

### Fixed
- Temporary Binance RTT, network and `-1021` preflight failures now keep the
  supervisor alive in fail-closed `PREFLIGHT_BACKOFF` instead of producing a
  traceback and systemd restart storm.
- Legacy signed reads perform one midpoint-based server-clock resynchronization
  and one newly signed retry after a definitive `-1021`; bounded exceptions and
  auth alerts never retain a signed query URL.
- Preflight failure classification, retry schedules and heartbeat-aware waits
  moved into `supervision.preflight_resilience`; the supervisor runtime remains
  below its previous architecture budget.
- Stable CONFIG, exchange-filter, persistent-HALT and unchanged recovery
  messages are rate-limited while heartbeat JSON remains fresh each cycle.
- Startup HALT evidence identifies the exact executed BUY, exchange order and
  quantity whose protection is missing.

### Verified
- Signed-read clock, preflight backoff, recovery, watchdog, dashboard and
  deployment regressions pass; compileall and the complete suite pass
  (712 tests).

## [2.20.70] — 2026-07-28

### Changed
- Worker CLI ownership and the main event loop moved from the execution-adapter
  runtime into `execution.worker.bootstrap`.
- The loop now receives an explicit mutable `WorkerRuntimeState` backed by the
  live runtime namespace, preserving SIGTERM updates, WebSocket transport
  replacement and SQLite connection rebinding without compatibility imports.
- The execution-adapter runtime shrank from 2456 to 1663 lines and no longer
  owns a `main` entry point.

### Verified
- Runtime-state, worker safety, recovery, accounting, deployment and
  architecture regressions pass; compileall and the complete suite pass
  (706 tests).

## [2.20.69] — 2026-07-28

### Changed
- Idempotent account-trade polling, FIFO synchronization, cursor advancement
  and AI fill attribution moved into `execution.worker.stats_sync`.
- Worker recovery and tests call the owning stats service directly through
  explicit runtime adapters; the worker coordinator shrank from 2597 to 2456
  lines.

### Verified
- Accounting restart/idempotency, worker recovery, protection, safety and
  exception-boundary regressions pass; the complete suite passes (702 tests).

## [2.20.68] — 2026-07-28

### Changed
- Holdings SELL placement moved from the worker coordinator into
  `execution.worker.holdings_service`; production and tests call the owning
  package service directly through explicit adapters.
- The worker runtime shrank from 2800 to 2597 lines.

### Verified
- Worker safety, financial exception-boundary and architecture regressions pass.

## [2.20.67] — 2026-07-28

### Changed
- BUY placement now executes directly from `execution.worker.buy_service`;
  callers and tests use the package API instead of a historical worker wrapper.
- CLI and ASGI launchers no longer replace their module identity through
  `sys.modules`, and obsolete AI-context, order and protection import facades
  were removed after production and test imports moved to their owning packages.
- The worker runtime shrank from 3107 to 2800 lines and its architecture budget
  was lowered to prevent the BUY orchestration returning to the monolith.

### Verified
- Worker safety, exception-boundary, accounting and architecture regressions
  pass, and the complete project suite passes (701 tests).

## [2.20.66] — 2026-07-28

### Changed
- Supervisor configuration and the plan-runner implementation now live in the
  `ladder_dragon.supervision` application package. Historical `bin` imports and
  commands remain thin compatibility facades for systemd and operators.
- Pure adaptive-entry and VWAP configuration policies were extracted from
  `bin/ai_supervisor.py`, reducing it from 5717 to 5433 lines without changing
  its public compatibility surface.
- Authoritative risk-snapshot construction, startup intent reconciliation and
  graceful child shutdown now execute from dedicated supervision services.
  The runtime retains thin compatibility wrappers and shrank from 5315 to 4825
  lines.
- SQLite migration ownership moved from `bin` to
  `ladder_dragon.persistence`; execution code no longer imports a CLI module.
- Supervisor, execution worker and dashboard implementations moved behind thin
  compatibility entry points. Recovery/risk/process/symbol policies, worker
  BUY/holdings/PANIC policies and dashboard factory/services/repositories now
  have explicit package boundaries.
- Order-journal models, canonical schema values and durable connection policy
  are separate from the compatibility class while atomic lifecycle methods
  retain their existing transactions.
- Prediction, AI context, LIMIT/MARKET/OCO/OTOCO placement, protection,
  Testnet/Mainnet verification and operator cancellation are grouped in
  technical packages with their historical imports and commands preserved.
- Added concise English docstrings to major supervisor, execution, replay,
  prediction, verification and dashboard nodes. Comments describe safety
  invariants and sequencing instead of restating obvious syntax.
- Added an architecture guide with dependency direction, package ownership and
  an explicit register of remaining monolith seams.

### Added
- Architecture regressions require package code to remain independent of
  `bin`, keep compatibility entry points thin, and prevent the three largest
  legacy runtime modules from growing beyond their current budgets.
- Added shared isolated runtime loaders under `tests/support`, strict
  non-growth budgets for every remaining coordinator and a documented
  no-automatic-cleanup policy for private local artifacts.
- Source-language regression rejects Cyrillic outside explicit localization
  files and requires English documentation on critical long-running nodes.

### Fixed
- Verification now blocks when an explicit 40-character `--expected-sha` does
  not exactly match the checked-out commit, instead of silently reporting the
  actual checkout as PASS.

### Verified
- Configuration, supervisor, strategy, migration, source-contract, deployment,
  accounting and architecture regressions pass (56 targeted tests for this
  extraction).
- Source compilation and the complete project test suite pass (700 tests).

## [2.20.65] — 2026-07-28

### Fixed
- OCO and OTOCO recovery now preserve an existing exchange order list when any
  verification read times out or disconnects. The uncertainty propagates to the
  existing fail-closed HALT boundary without issuing cancellation or creating
  replacement protection.
- A terminal TP/STOP leg with positive partial execution is recorded once by
  exchange order ID instead of being classified as ambiguous or as an exact
  closed lifecycle. Replacement protection is sized only for the confirmed
  residual BUY quantity.
- Managed-inventory telemetry subtracts normalized partial protection exits, so
  dashboard exposure does not continue to count quantity already sold.

### Changed
- The order journal schema is version 3 and adds an indexed, Decimal-text
  partial-protection-exit table with conflict detection and idempotent replay.

### Verified
- Recovery tests cover OCO and OTOCO read timeouts without cancellation,
  terminal partial STOP classification, ambiguous dual executions, idempotent
  residual accounting, and exact residual OCO sizing.
- Source compilation, restart/partial-fill/OCO/STOP/gap/idempotency regressions,
  complete project tests, and the release verification profile pass.

## [2.20.64] — 2026-07-28

### Security
- Signed POST, DELETE, PUT, and PATCH requests now make exactly one transport
  attempt. A network exception or Binance 5xx is returned as an unknown outcome
  for journal-based `clientOrderId` reconciliation instead of being replayed
  up to eight times.
- Binance `-2010 Duplicate order` no longer marks an intent `FAILED`; it keeps
  the intent unresolved until the existing exchange order is reconciled.
- HTTP 418 immediately arms a shared local cooldown for the full
  exchange-provided `Retry-After` interval. Requests are blocked locally during
  the ban instead of extending it with retries.
- HTTP 429 uses the same non-blocking local `Retry-After` cooldown, so the
  protection loop is not held inside a long sleep and the IP is not hammered.

### Changed
- Signed GET/HEAD retries are bounded to three attempts, reducing the maximum
  time a degraded exchange can hold the single-threaded protection loop.
- The first definitive `-1021` rejection performs one midpoint-adjusted
  `/api/v3/time` synchronization. Only then is the rejected request retried;
  failed synchronization remains fail-closed.

### Verified
- Transport regressions prove one mutation attempt for network loss and 5xx,
  bounded signed reads, 418 cooldown without another network request,
  secret-safe diagnostics, clock resynchronization, and duplicate-ID recovery.
- Source compilation, restart/partial-fill/OCO/STOP/gap/idempotency regressions,
  complete project tests, and the release verification profile pass.

## [2.20.63] — 2026-07-28

### Fixed
- Exact BUY/OCO/TP-or-STOP lifecycle closure now commits parent state, protection
  state, both metadata records, and normalized closure evidence in one SQLite
  transaction. Verified OCO legs and both protected states have an equivalent
  atomic transition.
- Reusing a `client_order_id` now succeeds only for the same immutable intent.
  Symbol, side, purpose, type, parent, metadata, quantity, and price conflicts
  fail closed without exposing metadata values in the exception.
- Active-intent deduplication compares quantity and price numerically with
  `Decimal`, so historical formatting or later Binance filter formatting cannot
  create a duplicate live intent.
- OCO leg lookup and exact-lifecycle telemetry now use indexed normalized
  tables instead of scanning and parsing every historical metadata document.
  The process reuses one thread-safe, fork-aware SQLite connection and selects
  WAL durability once per connection.

### Changed
- Exact journal history is retained indefinitely for audit and recovery.
  Performance no longer depends on deleting or automatically archiving CLOSED
  intents; destructive retention remains explicitly out of the runtime path.

### Verified
- Journal tests cover injected mid-transition crashes, idempotent and
  conflicting intent IDs, numeric deduplication, indexed evidence independent
  of legacy JSON, OCO recovery, exact TP/STOP closure, and secret-safe errors.
- Source compilation, relevant execution regressions, and the complete project
  test suite pass.

## [2.20.62] — 2026-07-28

### Added
- Added `DECISIONS.md` for concise, validated, reusable engineering decisions
  and `MISTAKES.md` for agent-caused failures with explicit impact, root cause,
  correction, and prevention.
- Repository agent instructions now require both learning records to be read
  before edits and updated when a successful invariant or a new mistake warrants
  a durable lesson.

### Verified
- Documentation-contract, agent-instruction, version-synchronization, source
  compilation, and complete project tests pass.

## [2.20.61] — 2026-07-28

### Changed
- Added one runtime safety and reporting reference.
  It covers BUY protection, flatten confirmation, HALT, SHADOW, inventory, FIFO PnL, Telegram, logs, and deployment.
- Synchronized the public project description, introduction, dashboard
  explanation, documentation index, and Raspberry Pi operator commands with
  the behavior shipped in 2.20.57 through 2.20.60.

### Verified
- Documentation-link, publication-asset, version-synchronization, source
  compilation, and complete project tests pass.

## [2.20.60] — 2026-07-28

### Fixed
- The dashboard no longer reports a numeric 24-hour FIFO realized PnL when a
  symbol sold in that window has incomplete lot history or unpriced commission
  provenance. It displays the metric as unavailable and names the excluded
  symbols instead of silently truncating excess SELL quantity.
- Cash flow and portfolio valuation remain available as separate metrics and
  are never relabelled as exact realized PnL.

### Verified
- Dashboard regressions cover exact complete-history PnL and fail-closed
  incomplete-history output. Frontend syntax, security, localization and
  deployment-asset checks pass.

## [2.20.59] — 2026-07-28

### Fixed
- The daily Telegram digest now isolates FIFO accounting by symbol. Symbols
  with incomplete history, unpriced commissions or unsupported quote
  provenance are listed under `Excluded symbols` while exact eligible-symbol
  totals are still delivered.
- Structural report failures now send one deduplicated English `BLOCKED`
  warning per report date. The warning contains no estimated financial figures,
  and no synthetic opening lot or zero cost basis is ever created.

### Verified
- Daily-digest regressions cover mixed valid/incomplete symbols, unpriced
  commissions, exact eligible-symbol PnL and deduplicated blocked alerts.

## [2.20.58] — 2026-07-28

### Fixed
- Filled BUY protection now validates the fresh Binance market relationship
  `TP > market > STOP > STOP_LIMIT` immediately before OCO submission. A
  crossed protection plan is never submitted as an inevitably rejected OCO.
- Any definitive LIVE OCO attach failure now triggers an idempotent emergency
  MARKET flatten, regardless of the non-LIVE single-TP fallback setting. The
  parent BUY is closed only after a complete `FILLED` response and durable
  journal update; partial, unknown or failed exits remain halted and unresolved.
- Advisory SHADOW evidence continues while execution is HALTED when the
  authenticated risk snapshot is healthy. It never starts workers or enables
  order mutations.
- Stable risk no-ops no longer flood journald: zero BUY cancellations are
  silent and allowlisted unvalued-asset diagnostics are rate-limited.

### Verified
- Regressions cover crossed OCO prices, complete and partial emergency
  flatten, journal closure, SHADOW collection under HALT and stable-log
  suppression. Executor, recovery, risk and numeric-boundary suites pass.

## [2.20.57] — 2026-07-28

### Changed
- The dashboard position view now uses responsive cards instead of a
  980-pixel-wide table. Market value, basis-dependent PnL and protection
  scopes remain readable on desktop and mobile without horizontal scrolling.
- Managed bot inventory and legacy account inventory are shown in separate sections.
  Managed protection reports exact protected and unprotected quantities.
  Legacy inventory is clearly outside bot control.
- Purchase-history provenance moved into an optional details disclosure.
  Internal status codes remain localized, while the primary view uses concise
  operator-facing labels in English and Russian.

### Verified
- Dashboard regressions verify the responsive card structure, exact managed
  protection remainder, localized labels, escaped dynamic content and
  collapsed cost-basis details. Dashboard security and deployment asset tests,
  Python compilation and the complete project suite pass.

## [2.20.56] — 2026-07-27

### Fixed
- Emergency gap flatten now derives the residual protected quantity from both
  OCO legs, cancels the breached list IDs and performs bounded authoritative
  polling until those lists disappear and the required balance is free.
- Gap flatten reports success only when a `FILLED` MARKET response confirms
  the complete expected quantity. Cancel-release timeout, partial execution,
  missing execution quantity and unknown outcomes persist a HALT with an exact
  operator-facing reason.
- Protection, panic flatten and managed holdings SELL no longer subtract one
  extra `minQty` after step-size rounding. A full step-aligned fill is
  protected or sold; only unavoidable sub-step exchange dust remains.
- LIVE `prefer-tp1` rejection now distinguishes a confirmed emergency flatten
  from an unconfirmed or partial one and catches transport failures locally
  before recording the persistent halt.
- Protection TP normalization now uses the same tick-direction as the
  authoritative OCO placement boundary (`ceil`) instead of lowering the target
  by one tick through an earlier `floor`.

### Verified
- Regressions cover delayed and never-completed OCO release, managed quantity
  mixed with legacy balance, partial TP residual selection, partial MARKET
  execution, transport failure, full step-aligned OCO/holdings quantities and
  TP tick direction.
- The isolated gap drill confirms full and partial STOP residuals, lost cancel
  acknowledgement, persistent halt and restart survival without network
  access. Executor/recovery/safety regression suites, Python compilation,
  whitespace checks and the complete 663-test project suite pass.

## [2.20.55] — 2026-07-27

### Fixed
- SQLite schema/opening races during dashboard restart now return a sanitized,
  retryable HTTP 503 with `Retry-After: 2`; database exceptions can no longer
  escape read-only endpoints as HTTP 500 responses.
- Dashboard SQLite connections now enforce URI read-only and `query_only`
  modes, so an early dashboard request cannot create an empty statistics
  database before the trading process initializes it.
- Filled-order compatibility endpoints no longer turn an unavailable database
  into a misleading empty result.
- Raspberry deployment readiness now waits up to 30 seconds for an
  authenticated database-backed dashboard request. The updater does not
  declare the dashboard ready merely because the process and non-database
  health endpoint are running.

### Security
- Deployment passes the dashboard readiness credential to `curl` over stdin,
  never through argv, logs or a temporary file. Error responses expose only a
  stable error code and exception class is limited to the protected service
  journal.

### Verified
- Dashboard regressions cover every trades/filled compatibility endpoint
  against an opened but not-yet-migrated SQLite database and prove HTTP 503,
  retry metadata and absence of SQLite details.
- Dashboard/deployment tests and shell syntax validation pass. Python
  compilation, whitespace checks and the complete 654-test project suite pass.

## [2.20.54] — 2026-07-27

### Fixed
- `TradeExecution.create()` now treats an omitted quote valuation for a
  non-zero commission as unpriced. Exact PnL, FIFO and inventory consumers
  fail closed instead of silently pricing an unknown fee at zero.
- Binance base-asset normalization now recognizes TUSD, GBP, AUD, BRL, JPY
  and DAI quote pairs in addition to the existing quote assets.
- Average-cost replay now rejects a SELL beyond known inventory by default.
  The two intentionally partial-history consumers opt into relaxed replay
  explicitly; exact daily reporting remains strict and blocks incomplete FIFO
  history.
- Portfolio returns are now additive natural-log returns.
  Correlation and covariance VaR align symbols by exact candle intervals.
  Configured VaR fails closed when an exposed symbol has insufficient history.
- Expected Shortfall now accepts only finite, non-negative loss magnitudes and
  validates its confidence range instead of silently converting profits to
  zero-valued losses.

### Changed
- Raspberry risk snapshots now retain Binance kline timestamps and only fetch
  VaR history when the configured VaR gate is active (or multi-symbol rolling
  correlation needs it). Example configuration and README risk semantics are
  synchronized with the implementation.

### Verified
- Regressions cover omitted commission valuation, newly supported quote
  assets, strict and advisory inventory replay, FIFO refusal of unpriced fees,
  natural-log returns, timestamp alignment and ordering, VaR horizon scaling,
  and Expected Shortfall input validation.
- Python compilation, whitespace checks and the complete 647-test project
  suite pass.

## [2.20.53] — 2026-07-27

### Fixed
- A lost `cancelReplace` acknowledgement now runs four bounded authoritative
  exchange reconciliations instead of treating one immediate
  `old=NEW/replacement=absent` snapshot as proof of failure. An unresolved
  outcome remains `UNKNOWN` and halts further mutations; it is never
  misreported as `FAILED`.
- Binance `cancelResult=FAILURE` with
  `newOrderResult=NOT_ATTEMPTED` is now classified as an exact no-op. Routine
  partial-fill versus re-anchor races no longer create a false symbol HALT.
- Reconciliation now accepts a replacement already reported as `FILLED`, as
  well as `NEW` and `PARTIALLY_FILLED`, and records both sides of the atomic
  exchange transition in the durable journal.

### Verified
- Cancel-replace regressions cover delayed exchange visibility, exhausted
  ambiguity with persistent HALT, transient reconciliation-query failure,
  structured no-op classification, immediate replacement fill, secret-free
  diagnostics, no mutation resubmission, hard CAP rejection and partial-fill
  rejection.
- Re-anchor, restart/recovery, idempotency, partial-fill and OCO/STOP regression
  suites pass. Python compilation, whitespace checks and the complete 634-test
  project suite pass.

## [2.20.52] — 2026-07-27

### Fixed
- Raspberry Pi watchdog recovery notifications now require a previously
  announced incident and two consecutive successful checks. A single transient
  heartbeat, DNS, TLS or Binance API probe failure remains an internal suspect
  state and no longer produces a misleading Telegram recovery message.
- Network and heartbeat incidents now retain independent deduplication state,
  so alternating event types cannot reset each other's notification cooldown.
- Confirmed failures emit one incident notification after the configured strike
  threshold; recovery state survives a service restart without repeating the
  same failure alert.

### Verified
- Watchdog regressions cover transient probe suppression, three-strike incident
  confirmation, two-success recovery hysteresis, offline outbox delivery and
  duplicate-alert suppression. Python compilation and the complete 629-test
  project suite pass.

## [2.20.51] — 2026-07-27

### Fixed
- SELL fill synchronization now persists one exact FIFO-consumption record per
  Binance `(symbol, trade_id)`. Re-reading `myTrades` after a restart between
  fill commit and cursor persistence cannot consume inventory lots twice.
- A repeated BUY or SELL trade ID with different quantity, price or order
  provenance now fails closed as a payload conflict instead of silently
  accepting divergent accounting data.
- FIFO consumption now plans the complete allocation before mutation and
  applies it under a SQLite savepoint. Insufficient inventory and mid-update
  database failures leave every lot unchanged, including on the autocommit
  statistics connection.
- Both worker and supervisor fill-reconciliation callers explicitly rollback
  failed lot synchronization before continuing. Non-positive or non-finite
  damaged OPEN rows are excluded from FIFO allocation.
- Added checksummed migration `007` for the durable
  `inventory_lot_consumptions` idempotency table.

### Verified
- Regression tests cover BUY payload conflicts, duplicate and conflicting SELL
  fills, the exact cursor-crash/restart replay window, insufficient inventory,
  a forced second-lot SQLite failure, damaged zero-quantity rows and repeatable
  migration from existing databases.
- FIFO, trade accounting, cost-basis import, migration, restart/recovery,
  partial-fill, OCO/STOP, safety and idempotency tests pass. Python compilation,
  whitespace checks and the complete project suite pass.

## [2.20.50] — 2026-07-27

### Changed
- Synchronized the README, introduction, Raspberry Pi runbook, release
  procedure and example environment with the implemented strategy-control,
  SHADOW/APPLY, release-manifest and deployment behavior.
- Documented that expectancy SHADOW retains authoritative fee accounting.
  It does not export the execution edge.
  Regime hold time starts when the state machine starts.
  Managed inventory requires an explicit hard CAP.
- Corrected the signed release order so the verification manifest is generated
  from the final signed candidate commit, attached to the GitHub release and
  copied to the Pi before the read-only post-deployment profile.
- Clarified the difference between execution safety and production approval.
  Attribution-only unresolved fills do not block execution after protection reconciliation.
  They still block RAG, approval, and the Pi approval profile.
- Corrected Testnet smoke commands, prediction database paths and manual test
  service handling so the watchdog cannot restart `mybot` during an isolated
  test run. Release commands now invoke the project virtual-environment
  interpreter explicitly instead of relying on a platform-dependent `python`
  alias or an incomplete system Python installation.

### Verified
- Documentation and deployment regression tests, product-version consistency,
  Python compilation and the complete project test suite pass.

## [2.20.49] — 2026-07-26

### Fixed
- Expectancy SHADOW no longer exports `BOT_REQUIRED_EDGE_PCT` to the worker,
  so observation mode cannot change guarded SELL targets or execution plans.
  Child startup also removes any stale inherited value before APPLY may add
  the freshly calculated authoritative edge.
  Authoritative side-specific commission rates remain available in every mode
  solely for exact fee accounting.
- Regime `min_hold_sec` now starts at state-machine creation using the monotonic
  process clock. Supervisor restarts on long-running hosts can no longer bypass
  the initial recovery hold, while zero-duration test/rollback policies remain
  immediate.
- Enabled inventory/regime CAP scaling with no positive `BOT_CAP_PER_ORDER`
  now emits an explicit `CAP-SCALING-INACTIVE` diagnostic instead of silently
  doing nothing.

### Verified
- Regression tests prove SHADOW child environments omit the execution edge,
  APPLY includes it, fee-rate accounting remains available, initial recovery
  timing is independent of host uptime, and missing CAP diagnostics are exact.
- Focused prediction, strategy controls, Risk Manager, executor,
  restart/recovery and OCO/STOP tests pass. Python compilation, whitespace
  checks, and the complete project test suite pass.

## [2.20.48] — 2026-07-26

### Fixed
- STRATEGY prediction evidence now uses an explicit zero-PnL
  `NO_TRADE`/USDT baseline. Missing REANCHOR baselines fail closed instead of
  substituting the candidate outcome, so a genuinely positive baseline edge
  can be measured without look-ahead.
- Inventory skew requires a dedicated managed-inventory hard CAP for each
  symbol (or the explicit managed global limit). It no longer inherits the
  portfolio CAP, and missing evidence reduces APPLY sizing to zero.
- Expectancy telemetry now reports whether both configured minimum net edge
  and TP satisfy the authoritative two-sided fee/slippage floor. APPLY keeps
  BUY disabled when the configuration is below that floor.
- The BUY VWAP premium gate now uses exact Decimal Schmitt hysteresis. Boundary
  noise such as `1.0031` around a `1.0030` limit no longer toggles BUY.

### Verified
- Focused prediction, no-look-ahead, strategy approval, inventory, expectancy,
  VWAP, Risk Manager, executor, recovery, OCO/STOP and fail-closed regressions
  pass.
- Python compilation, whitespace checks, and the complete project test suite
  pass.

## [2.20.47] — 2026-07-26

### Added
- Added a full-page, publication-safe dashboard preview to the README and
  introduction. All account-specific balances, quantities, prices, order and
  decision identifiers, process data, log timestamps, and infrastructure
  fingerprints were replaced with explicit synthetic demonstration values.
- Marked the preview `DEMO · SANITIZED` so documentation readers cannot
  mistake it for live trading evidence. All visible interface text is English.

### Verified
- Documentation asset references, release version consistency, PNG metadata,
  source-image exclusion, Python compilation, and the complete project test
  suite pass.

## [2.20.46] — 2026-07-26

### Added
- Added a fail-closed FIFO regime report that compares exact strategy net PnL
  with buy-and-hold and USDT, including realized drawdown, fill rate and sample
  coverage without using future or stale regime snapshots.
- Added an authenticated Binance commission schedule and an exact two-sided
  edge floor covering BUY/SELL fees, BUY/SELL slippage and a configurable
  safety multiplier. Ordinary entries and exits can be observed as
  `LIMIT_MAKER` candidates while emergency flattening remains unchanged.
- Added a hysteretic `RANGE`, `TREND_UP`, `TREND_DOWN`, `PANIC`, `RECOVERY`
  execution state machine and exact managed-inventory skew beneath the
  immutable hard CAP.
- Added multi-window correlation clusters and fail-closed per-symbol L2
  spread/depth eligibility for controlled multi-symbol diversification.

### Changed
- The transparent logistic regime model is published as a SHADOW challenger
  beside the deterministic baseline and DeepSeek recommendation.
- Every new expectancy, regime, inventory, maker and cluster control defaults
  to `SHADOW`. `APPLY` also requires the exact
  `BOT_STRATEGY_CONTROLS_APPROVED=YES` acknowledgement and a passing
  chronological lower-CI/Holm/regime/drawdown/fill-rate gate; otherwise new
  BUYs are blocked while existing protection and SHADOW collection continue.

### Verified
- Exact Decimal unit tests cover the two-sided fee floor, inventory skew,
  regime hysteresis, FIFO attribution, no-look-ahead behavior, dynamic
  correlation clusters and liquidity rejection.
- Prediction, AI statistical challenger, Risk Manager, executor protection,
  restart/recovery, OCO/STOP, WebSocket trading, safety and module-boundary
  regressions pass. Python compilation and whitespace checks pass.
- The complete suite passes all `605` project tests.

## [2.20.45] — 2026-07-26

### Fixed
- The position table now translates inventory provenance, managed/legacy
  coverage and gap-protection reason codes instead of exposing internal API
  identifiers such as `partial_inventory_lots`.
- Unknown future position codes use a localized safe fallback while the stable
  machine-readable values remain unchanged in the read-only API.

### Verified
- Position-localization regressions, JavaScript syntax and dashboard asset
  checks pass.
- The complete suite passes all `594` project tests; Python compilation and
  whitespace checks pass.

## [2.20.44] — 2026-07-26

### Fixed
- Mixed SOL inventory now reports managed OCO coverage and legacy unmanaged
  quantity separately. A managed `confirmed` state no longer implies that the
  full account position is protected.
- Dashboard average entry, unrealized PnL and drawdown now require sourced
  inventory lots to cover the full Binance account quantity. Partial legacy
  history is reported explicitly instead of producing a misleading combined
  loss estimate.
- User Data Stream telemetry now distinguishes cumulative observation time
  from the duration of the current WebSocket session.
- BUY candidates are ranked by descending price before the target-count limit
  is applied, so the exact adaptive closest maker level is selected instead of
  a deeper ladder level that happened to appear first.
- WebSocket trading requests now use the same Binance-server-adjusted clock as
  REST requests, preventing local NTP drift from splitting transport behavior.
- WebSocket response waits now have one monotonic request deadline that cannot
  be extended by unrelated frames. A matching success frame must contain
  status `200` and an object result or it fails closed as an unknown outcome.

### Changed
- BUY placement emits a sanitized `BUY-PRIORITY` event with the selected price,
  current-market gap and candidate count. Re-anchor remains SHADOW and all CAP,
  reserve, market-freshness, fee/slippage, OCO and statistical gates remain
  authoritative.

### Verified
- All `11` WebSocket trading regressions pass, including server-clock wiring,
  unrelated-frame deadline exhaustion and malformed success responses. Python
  compilation, JavaScript syntax and whitespace checks pass.
- The complete suite passes all `593` project tests.

## [2.20.43] — 2026-07-26

### Security
- AI provider responses are now streamed with a 64 KiB decoded-body ceiling,
  an early `Content-Length` rejection, strict UTF-8 decoding, and guaranteed
  connection closure. Oversized or malformed responses fail closed to the
  deterministic strategy without logging response content.
- All dynamic SQLite table, view, and column identifiers now pass one strict
  validator and are quoted before interpolation. Migration column declarations
  use a narrow allowlisted grammar.
- AI plan-runner symbols are validated as Binance identifiers before any
  network request or child-process launch.

### Fixed
- User Data Stream observer state updates, persistence, and snapshots now use
  an observer-owned reentrant lock, preventing mixed-session telemetry reads.
- Dashboard SQLite reads now wait up to five seconds for short WAL checkpoint
  or writer contention instead of failing after one second.

### Changed
- Project rules now require bounded untrusted HTTP parsing and validated
  SQLite identifier interpolation.

### Verified
- Added fail-closed tests for concurrent stream snapshots, compressed/body
  size overflow, hostile SQL identifiers and declarations, dashboard busy
  timeout, and invalid CLI symbols.
- The complete suite passes all `583` project tests; Python compilation and
  whitespace checks pass.

## [2.20.42] — 2026-07-26

### Fixed
- Star History now reads the paginated official GitHub GraphQL stargazer
  connection, which is compatible with the workflow installation token.
- Generation fails closed when pagination is incomplete or the returned
  history count differs from GitHub's authoritative `stargazerCount`.

### Verified
- Added a two-page GraphQL regression fixture covering cursor propagation,
  exact-count reconciliation, and token isolation.
- The complete suite passes all `575` project tests; Python compilation and
  whitespace checks pass.

## [2.20.41] — 2026-07-26

### Fixed
- Replaced the frozen zero-star README snapshot and failing third-party Star
  History endpoint with a chart generated from the official GitHub Stargazers
  API.

### Added
- A daily GitHub Pages workflow publishes the live Star History SVG without
  creating or updating a metrics branch.
- The generator publishes only dates and cumulative counts; GitHub account
  names and API credentials are excluded from the SVG and workflow logs.

### Verified
- Generator tests cover cumulative history, privacy, malformed input, and
  exact immutable GitHub Pages Action pins.
- The complete suite passes all `574` project tests; Python compilation and
  whitespace checks pass.

## [2.20.40] — 2026-07-26

### Changed
- Consolidated the four outstanding GitHub Actions dependency branches into
  one release: `actions/checkout` 7.0.1, `actions/setup-python` 7.0.0,
  `gitleaks-action` 3.0.0, and TruffleHog 3.96.0.
- All workflow dependencies remain pinned to immutable commit SHAs while the
  cumulative `main` branch remains the single source for deployable code.

### Verified
- Workflow regression tests require the exact reviewed commit SHA for every
  consolidated action in both applicable jobs.
- The complete suite passes all `572` project tests; Python compilation and
  whitespace checks pass.

## [2.20.39] — 2026-07-26

### Fixed
- Restored the missing Raspberry Pi `dashboard.css` and `dashboard.js`
  publication that caused the dashboard to render as unstyled HTML with empty
  runtime values.
- Raspberry install and update now compare every published dashboard asset
  with the exact verified release checkout and fail closed on a missing or
  hash-mismatched file.

### Changed
- The Pi verification profile now audits HTML, CSS, JavaScript, localization,
  icons, Chart.js vendor files, and the changelog as one immutable dashboard
  asset set.
- Project rules now require exact post-deployment dashboard asset integrity.

### Verified
- Dashboard asset regression tests cover both a missing CSS file and modified
  JavaScript content.
- The complete suite passes all `572` project tests; Python compilation and
  whitespace checks pass.

## [2.20.38] — 2026-07-26

### Fixed
- Tag-triggered GitHub jobs now force-refresh the event tag from the canonical
  remote tag namespace after checkout. This replaces GitHub's synthesized
  lightweight event ref with the signed annotated object before continuity
  verification.

### Verified
- Workflow regression assertions require both test and audit jobs to restore
  the exact canonical tag ref on tag events.
- The complete suite passes all `571` project tests; Python compilation and
  whitespace checks pass.

## [2.20.37] — 2026-07-26

### Fixed
- GitHub Actions now fetches complete tag objects in both jobs. Tag-triggered
  continuity checks therefore inspect the signed annotated tag instead of the
  lightweight checkout ref synthesized for the event.

### Verified
- Added a workflow regression assertion requiring `fetch-tags: true` on both
  full-history checkouts.
- The complete suite passes all `571` project tests and Python compilation and
  whitespace checks pass.

## [2.20.36] — 2026-07-26

### Added
- Added a mandatory release continuity check to the shared local/release
  verification harness and GitHub Actions. It emits the previous/current
  release identities and complete included-commit list as a release manifest.
- Added a versioned strict-lineage baseline and schema. Historical changelog
  gaps remain explicitly legacy; every release after `v2.20.35` must be the
  direct Semantic Version successor on annotated linear tags.

### Changed
- Pi verification now requires an explicit reviewed GitHub SHA and compares it
  with deployed HEAD, fetched upstream and the SHA-linked PASS release artifact.
- Extended project and release rules so a skipped version, repeated version
  bump, unversioned post-tag commit or nonlinear release cannot be published.

### Security
- Release continuity and Pi SHA mismatches fail closed with exit status `2`.
  The manifest contains commit identifiers only and cannot include child output,
  environment values, signed URLs or secrets.

### Verified
- Added regression coverage for a valid next release manifest, skipped version,
  late unversioned commit, synthetic pull-request merge and missing Pi GitHub
  SHA.
- The complete suite passes all `571` project tests; Python compilation, shell
  and JavaScript syntax, SVG validation and whitespace checks pass.

## [2.20.35] — 2026-07-26

### Changed
- Moved the Star history chart from the README opening to the final content
  section immediately before documentation and license links.

### Verified
- The README regression test now fixes the Star history section below the
  engineering content and above the final documentation section.
- The complete suite passes all `567` project tests; Python compilation, SVG
  validation, and whitespace checks pass.

## [2.20.34] — 2026-07-26

### Fixed
- Replaced the failing third-party Star History SVG, which returned HTTP 500
  for a repository with no stars, with a repository-owned chart that GitHub can
  render reliably. The chart is now visible near the top of the README.

### Added
- Added a live GitHub stars badge and retained a link to the interactive Star
  History page for use once public history exists.

### Verified
- The README regression test confirms the bundled chart and live badge are
  present and the failing external SVG endpoint is absent.
- The SVG passes XML validation and renders at its declared `960 × 300`
  dimensions. The complete suite passes all `567` project tests.

## [2.20.33] — 2026-07-26

### Fixed
- Risk-blocked LIVE operation now stops every execution worker while continuing
  rate-limited read-only AI and prediction SHADOW collection from a healthy,
  authenticated snapshot. The collector cannot clean up, roll, re-anchor,
  flatten, start a worker, or submit/cancel an order.
- Split unresolved fills into `ATTRIBUTION` and `INVENTORY` scopes. Attribution
  gaps remain excluded from RAG and block AI readiness, while only unresolved
  inventory/protection blocks deterministic BUY execution after authoritative
  reconciliation. Unknown and legacy schemas remain inventory fail-closed.
- Reused a known empty Binance open-order snapshot during BUY blocking instead
  of converting it to an extra authenticated `/openOrders` request.
- Supervisor shutdown now waits up to a bounded configurable timeout for every
  supervisor process to exit after `SIGTERM`, allowing its existing child
  cleanup to finish before systemd's outer timeout.
- Dashboard GitHub status now refreshes every five minutes by default, includes
  its check age, and explicitly reports a stale last-known result when refresh
  fails instead of claiming that an old commit is current.

### Changed
- Enabled the notification-only Binance User Data Stream observer by default in
  LIVE after authenticated preflight. It remains non-authoritative, cannot
  mutate trading state, and can be explicitly disabled operationally.
- Dashboard AI evidence now shows unresolved attribution and inventory counts
  separately.

### Security
- Blocked SHADOW collection requires a healthy authenticated risk snapshot and
  remains disabled during HALT or authentication backoff. Damaged unresolved
  scope values and old schemas are classified as inventory risk.
- Added fail-closed regression coverage proving blocked SHADOW cannot reach
  order mutation and that a known empty order snapshot cannot trigger another
  signed REST read.

### Verified
- All `185` focused AI, safety-gate, dashboard, deployment, schema, no-mutation,
  and no-extra-REST regression tests pass.
- All `144` recovery, partial-fill, OCO/STOP, gap, restart, idempotency,
  User Data Stream, Risk Manager, prediction, and verification-harness tests
  pass.
- The complete suite passes all `566` project tests; Python compilation, shell
  syntax, dashboard JavaScript syntax, and whitespace checks pass.

## [2.20.32] — 2026-07-26

### Added
- Added a README Star History chart with a link to the interactive public
  GitHub star timeline.

### Verified
- All `58` README, version, and deployment-asset regression tests pass.
- The complete suite passes all `557` project tests, and the complete Python
  source tree compiles successfully.

## [2.20.31] — 2026-07-26

### Added
- Added one idempotent English Telegram trading digest at 08:00 `Asia/Almaty`.
  One message reports yesterday and the last 7 and 30 complete days.
  It includes fills, valued fees, cash flow, and realized FIFO net PnL.
- Added a hardened systemd oneshot and persistent timer. The report reads the
  trade database in SQLite read-only mode, stores only its last successful
  report date, and never changes orders, HALT state, configuration, or Binance.

### Changed
- Reworked the README opening into a product-oriented overview with a concise
  value proposition, verified capability badges, problem/response mapping,
  operating flow, trust boundaries, navigation, and a clearer quick start.
- Moved the dashboard, help, and browser quick-start CSS plus dashboard
  JavaScript into dedicated static files. Deployment now installs those assets,
  and the script CSP no longer depends on a fragile inline SHA-256 hash.

### Security
- The digest blocks instead of publishing misleading PnL when FIFO history is
  incomplete, a commission lacks an exact quote value, the database is
  unavailable, or quote assets cannot be combined safely. Cash flow is
  explicitly labeled as not profit.
- HTML pages contain no inline style blocks, inline script bodies, or static
  `style` attributes. Dashboard scripts remain same-origin under CSP.

### Verified
- All `107` focused digest, dashboard, deployment, CSP, and Telegram regression
  tests pass.
- The new Python source compiles and `node --check FRONT/dashboard.js` passes.
- The complete local suite passes all `557` project tests.
- The pre-commit `release` harness passes numeric and tracked-secret audits,
  plus `18` replay, `21` walk-forward, `98` recovery and `59`
  migration/deployment regression checks (`753` total test executions).

## [2.20.30] — 2026-07-26

### Fixed
- Stopped treating a terminal Binance OCO (`ALL_DONE`) as reusable protection.
  Both exchange legs must now be active before an existing or newly submitted
  OCO can return to journal state `PROTECTED`.
- Added exact terminal OCO classification.
  One authoritative filled SELL leg closes the BUY lifecycle as TP or STOP.
  Two canceled zero-fill legs permit only the normal protected-recovery path.
- Removed the journal-only shortcut from restart recovery. A locally
  `PROTECTED` OCO is now queried and its two exact exchange legs are verified
  before the executor accepts it.
- Published the bounded, signature-redacted recovery reason in runtime and
  dashboard risk telemetry instead of the generic
  `pre-RUNNING recovery incomplete` message.

### Security
- Ambiguous, partially terminal or malformed OCO state remains fail-closed.
  The fix never converts canceled legs into evidence of protection and never
  closes a lifecycle without one exact filled Binance SELL leg.

### Verified
- All `141` focused OCO, restart, worker protection, supervisor safety and
  fail-closed regression tests pass; source compilation also passes.
- The complete local suite passes all `552` project tests.
- The pre-commit `release` harness passes numeric and tracked-secret audits,
  plus `18` replay, `21` walk-forward, `98` recovery and `58`
  migration/deployment regression checks.
- Authenticated read-only Pi evidence reproduced the defect safely: the
  historical OCO was `ALL_DONE`, both SELL legs were `CANCELED`, and both had
  exactly zero executed quantity.

## [2.20.29] — 2026-07-26

### Fixed
- Connected the exact ATR/regime-adjusted `DEV_BUY_PCT` to the actual initial
  ladder. The previous child environment value did not affect placement, so
  the nearest BUY remained about 0.5% below a rising market until TTL or PANIC.
- Reversed the directional entry defaults: `UP` now places the nearest BUY
  closer while remaining strictly below market, and `DOWN` widens the gap.
  TP is not narrowed and must cover the exact minimum-profit guard within its
  configured ceiling or the cycle fails closed.
- Added a relative Decimal floor to the ATR PANIC band so a tiny one-minute ATR
  cannot classify ordinary sub-0.1% movement as PANIC. The separate abrupt-drop
  trigger and meaningful downside protection remain active.
- Enforced real-only RAG retrieval in every mode and synchronized the example
  configuration and documentation.

### Security
- Re-anchor remains SHADOW: Raspberry evidence has a negative lower confidence
  bound and fails the production gate, so this release does not allow it to
  chase price or bypass the existing approval.

### Verified
- All `181` focused supervisor, prediction, re-anchor, PANIC, RAG, deployment
  and fail-closed safety tests pass; source compilation also passes.
- The complete local suite passes all `545` project tests.
- The pre-commit `release` harness passes compilation, all project tests,
  numeric and tracked-secret audits, plus `18` replay, `21` walk-forward,
  `92` recovery and `58` migration/deployment regression checks.

## [2.20.28] — 2026-07-26

### Fixed
- Restricted startup and periodic ladder cleanup to BUY orders, so TTL and
  off-ladder cleanup can never cancel protective SELL, OCO or OTOCO legs.
- Added startup and continuous authoritative reconciliation of every journal
  `PROTECTED` BUY against the exact Binance order list and both active SELL
  legs. A mismatch now creates a manual HALT and blocks new BUY orders.
- Blocked new BUY orders while any bot fill remains unresolved. Late or
  restart-time exchange-order mappings atomically move matching historical
  fills into the real execution ledger before the block can clear.
- Separated open canary quantity from legacy account inventory in dashboard
  telemetry and exposed journal-versus-Binance protection mismatches.
- Labeled historical virtual RAG documents as archived and non-retrievable;
  the active virtual counter remains zero under the real-only policy.
- Updated the dashboard inline-script CSP hash after the lifecycle telemetry
  rendering change.

### Security
- Exact TP/STOP lifecycle evidence still advances only after a confirmed
  terminal exchange SELL fill. Missing protection, damaged reconciliation
  data or an unresolved bot fill fails closed and cannot be bypassed by AI.

### Verified
- `135` focused AI execution, order recovery, supervisor safety, dashboard and
  real-only RAG tests pass; source compilation also passes.
- The `release` harness passes all `538` project tests, numeric and secret
  audits, plus `18` replay, `21` walk-forward/approval, `86` recovery and `58`
  migration/deployment regression checks.

## [2.20.27] — 2026-07-26

### Added
- Added one fail-closed verification harness with `local`, `release`,
  `testnet`, `pi` and separately confirmed `mainnet-canary` profiles.
- Added an owner-only, versioned JSON artifact containing commit and product
  identity, allowlisted check metrics, source hashes, replay errors, execution
  latency percentiles, unresolved fills and exact lifecycle evidence.
- Added JSON Schema v1 for verification reports and regression coverage for
  unknown profiles, missing checks, venue confirmations and output secrecy.

### Changed
- GitHub's Python 3.10/3.11/3.12 matrix now invokes the same `local` harness
  used by developers instead of calling pytest directly.

### Security
- Child command output and environment values are never persisted in harness
  artifacts. Testnet authentication, Testnet mutation and Mainnet mutation
  retain separate explicit confirmations; the Pi profile is read-only.
- Corrected the tracked-secret scanner so ordinary lowercase code identifiers
  ending in `private_key` cannot be mistaken for uppercase credential
  assignments; real uppercase credential assignments remain covered.

### Verified
- The `local` harness passes source compilation, all `530` project tests, the
  numeric-boundary audit and tracked-secret scan.
- The `release` harness also passes `18` replay, `21` walk-forward/approval,
  `82` recovery and `58` migration/deployment regression checks. Both
  owner-only artifacts satisfy the report's structural schema regression.

## [2.20.26] — 2026-07-23

### Added
- Added a public-only persistent market-data actor for real-time `bookTicker`,
  `aggTrade`, `depth20@100ms` and closed one-minute kline events. Immutable
  Decimal snapshots include incremental EMA20, ATR14, VWAP, depth imbalance
  and signed trade flow.
- Added independently approved freshness, spread, market-move and net-edge
  gates. `SHADOW` records results without changing the plan; LIVE `APPLY`
  fails closed unless its explicit operator approval is present.
- Added durable Binance OTOCO placement with exact working BUY, TP and STOP
  identities, three-order exchange verification, restart recovery and a
  fail-closed partial-fill transition to separate OCO protection.
- Added a persistent Binance Spot WebSocket API mutation transport with HMAC
  and owner-only Ed25519 key support. Unknown ACKs are never blindly retried
  and continue through existing client/list reconciliation.
- Added monotonic phase telemetry for market receipt, feature calculation,
  risk decision, journal commit, request send, exchange ACK, fill receipt,
  protection activation and atomic cancel-replace acknowledgement.

### Changed
- User Data Stream events now wake the tracked-order mailbox immediately and
  run authoritative protection reconciliation before indicator work and other
  periodic REST checks. The one-second interval remains only for housekeeping.
- Adaptive BUY re-anchor `APPLY` now defaults to journaled Binance
  `cancelReplace` with `STOP_ON_FAILURE` and `ONLY_NEW`. It stops the symbol
  worker first, refuses partial fills, preserves the hard CAP and reconciles
  every ambiguous response.
- Added `cryptography==49.0.0` and regenerated CI/Raspberry hash-locked
  requirements for Ed25519 request signing.

### Security
- All acceleration layers remain `OFF` by default and each LIVE `APPLY` mode
  requires a separate exact `YES` approval. Market streams receive no
  credentials, latency records contain no order identity or secret, and an
  Ed25519 PEM must be an absolute owner-only file.

### Verified
- The complete local suite passes with `520` tests. Source compilation,
  focused restart/partial-fill/OCO/STOP/idempotency tests and
  `git diff --check` pass.

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
- User Data Stream frames now persist a sanitized transport activity timestamp.
  The dashboard uses it for stale detection.
  A quiet healthy connection no longer becomes stale because an order event is old.

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
- The recovery exit requires a verified transition, LIVE mode, and no tracked BUY.
  Active PANIC, unknown PANIC, or a retained BUY fails closed.
  The replacement worker runs all safety checks again.
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
- Re-anchor remains `OFF` by default.
  `SHADOW` records candidates without cancellation.
  `APPLY` does not cancel partial BUYs, SELLs, or OCO legs.
  It does not follow a falling ladder.
  A confirmed refresh restarts only the applicable worker.

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
- Added a least-privilege public depth recorder and an hourly systemd timer.
  It records 15-minute SOLUSDT samples and retains seven days by default.
  It uses an exclusive lock and removes Binance and AI credentials.
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
- Added a preview-first legacy holdings cost-basis import.
  It reconstructs FIFO lots from exact trade identifiers and commissions.
  It requires quantity agreement and revalidates live state before an atomic apply.
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
- OCO protection records retain the two verified leg identifiers and types.
  A natural canary cycle requires one fully `FILLED` exact TP or STOP leg.
  Partial and unresolved fills cannot satisfy the promotion gate.
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
- Active BUY intents now retain a throttled, durable market-price range.
  PANIC and TTL logs include age, TTL, distance, minimum price, quantity, and cancellation reason.
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
- Added a separate bounded Mainnet acceptance canary for `SOLUSDT`.
  It performs a real BUY, OCO, journal reload, and cleanup SELL cycle.
  It cannot exceed `10 USDT` and preserves the configured reserve.

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
- The hardened backup service retains only the required filesystem capabilities.
  Release 2.10.73 removed all capabilities.
  Thus, systemd failed with status 126 on hosts that used a `0750` bot home.
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
- Added regressions for configuration, CSRF, CSP, dependencies, history scans, Actions, systemd, Binance rejections, logs, and recovery.
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
