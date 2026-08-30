# Engineering decisions

### 2026-08-31 — Grant sandbox capabilities from the destination ownership model

- **Context:** a root service with an empty capability set cannot bypass mount-owner permissions on external storage.
- **Decision:** grant only DAC override and file-owner capabilities to the encrypted L2 retention service.
- **Why it worked:** the service can publish and verify archives without receiving unrelated administrative capabilities.
- **Reuse:** every sandboxed root service that writes to a mount owned by filesystem options.

### 2026-08-31 — Delegate external permissions to filesystem mount options

- **Context:** the encrypted backup disk uses exFAT, which does not implement Unix mode changes.
- **Decision:** create external directories without chmod and enforce permissions through reviewed mount options.
- **Why it worked:** local status paths retain strict modes, while external encrypted archives remain writable and verified.
- **Reuse:** every external storage workflow that supports filesystems without Unix permission semantics.

### 2026-08-31 — Freeze evidence cohorts before recurring planning

- **Context:** recurring planning could count incomplete context and create another rolling draft set.
- **Decision:** count only exportable context paths and persist one cohort identity before future planning cycles.
- **Why it worked:** progress now matches import readiness, while later data cannot replace the reviewed source set.
- **Reuse:** every recurring producer of immutable selection or confirmation evidence.

### 2026-08-30 — Bound evidence paths by provider session lifetime

- **Context:** one historical block exceeded the exchange's maximum WebSocket connection lifetime.
- **Decision:** build stability blocks from source-disjoint paths that each fit inside one verified provider session.
- **Why it worked:** reconnects censor only unfinished paths, while later sessions can contribute new independent paths.
- **Reuse:** every evidence design that depends on an externally limited session.

### 2026-08-30 — Express backup retention in exact minutes

- **Context:** `find -mtime +N` rounds age down and extends an N-day retention policy by one day.
- **Decision:** convert configured days to minutes before local and external archive selection.
- **Why it worked:** deployment tests prohibit rounded day selectors in the backup workflow.
- **Reuse:** every retention contract that promises a precise duration.

### 2026-08-30 — Pin each live SQLite backup snapshot

- **Context:** page batches restarted when continuous WAL writes changed a large source database.
- **Decision:** copy all remaining pages in one backup step and close both connections immediately.
- **Why it worked:** deployment tests prohibit paginated backup and require explicit connection closure.
- **Reuse:** every online backup of a database with continuous production writes.

### 2026-08-30 — Prove empirical bucket reachability before confirmation

- **Context:** zero-inflated calibration values could create an empty volatility bucket.
- **Decision:** split the positive tail when required and require minimum selection coverage in every future bucket.
- **Why it worked:** tests accept a zero-inflated cohort with three populated buckets and reject insufficient separation.
- **Reuse:** every empirical policy that requires categorical coverage during later confirmation.

### 2026-08-30 — Start destructive retention from successful backup completion

- **Context:** clock ordering did not prove that the current encrypted backup had completed.
- **Decision:** trigger retention from backup success and retain the daily timer as a safe retry.
- **Why it worked:** deployment tests bind the backup unit to the guarded retention service.
- **Reuse:** every destructive maintenance task that depends on a fresh recoverable artifact.

### 2026-08-30 — Bound derived telemetry with durable time buckets

- **Context:** minute-level legacy snapshots grew rapidly without increasing independent experiment evidence.
- **Decision:** store one legacy snapshot per kind, symbol, and five-minute SQLite bucket.
- **Why it worked:** tests prove restart-safe suppression without touching selection or confirmation evidence.
- **Reuse:** every disposable telemetry stream whose sampling rate exceeds its analytical cadence.

### 2026-08-30 — Prime asynchronous evidence without claiming consumption

- **Context:** a background PANIC refresh can finish after the runtime already consumed its inputs.
- **Decision:** prime missing state without a journal row, then attest the exact state consumed by the next cycle.
- **Why it worked:** tests prove warm-up creates no false gap and the next cycle writes available evidence.
- **Reuse:** every asynchronous observer that attests inputs consumed by a synchronous decision loop.

### 2026-08-29 — Reclaim backup capacity before collection

- **Context:** interrupted backup staging and expired local copies can consume the capacity required by the next encrypted archive.
- **Decision:** prune eligible local, public, and external data before writing, while preserving the newest completed archive.
- **Why it worked:** tests require preflight ordering, strict staging grammar, minimum staging age, and immediate public index reconstruction.
- **Reuse:** every capacity-sensitive archive workflow with atomic publication and interrupted-run recovery.

### 2026-08-29 — Bound host recovery with persistent authority

- **Context:** network recovery must not create reboot loops or interrupt protected host operations.
- **Decision:** combine monotonic failure windows, a durable reboot latch, shared maintenance locks, and a persistent notification outbox.
- **Why it worked:** offline tests reject premature reboots, repeated requests, corrupt state, and mutations during locked backups.
- **Reuse:** unattended hosts that need bounded recovery without changing application safety controls.

### 2026-08-28 — Record historical context at its observation boundary

- **Context:** public depth alone cannot establish historical fees, filters, or the runtime PANIC input.
- **Decision:** record narrow source projections with observation times, expiry, classifier identity, and append-only hashes before replay uses them.
- **Why it worked:** tests connect the observer to replay and reject future context, missing sources, state-change races, and session gaps.
- **Reuse:** every historical model that depends on inputs absent from its public market archive.

### 2026-08-27 — Separate pre-fill selection from post-fill diagnostics

- **Context:** a later diagnostic gap discarded valid causal L2 evidence captured before a filled episode.
- **Decision:** combine source-hashed pre-fill L2 with the immutable eligible terminal strategy result.
- **Why it worked:** later gaps remain visible, while unrelated post-fill completeness cannot erase causal selection evidence.
- **Reuse:** every entry filter selected from data available before its execution boundary.

### 2026-08-26 — Separate proven absence from unresolved order submission

- **Context:** an immediate order query can return not-found before an accepted order becomes visible.
- **Decision:** reconcile by stable client identity through bounded order, open-order, and historical-order reads.
- **Why it worked:** proven absence consumes one attempt, while unresolved mutation permanently closes the batch.
- **Reuse:** every bounded live validation that receives no authoritative mutation response.

### 2026-08-26 — Replay entry vetoes on independent L2 evidence

- **Context:** overlapping fills and instant row removal overstated a future veto's benefit.
- **Decision:** use source-hashed L2 features, independent paths, stability blocks, and chronological cancel replay.
- **Why it worked:** late cancels retain their fills, while successful cancels release capacity at exchange arrival.
- **Reuse:** every counterfactual order policy selected from correlated market observations.

### 2026-08-25 — Change one exit axis in a new evidence generation

- **Context:** version 21 showed an unfavorable reward-to-loss ratio under its fixed 60-basis-point target.
- **Decision:** preserve version 21 and test an 80-basis-point target in version 22.
- **Why it worked:** the new fingerprint records maximum favorable and adverse bid excursions without changing decisions.
- **Reuse:** every financial parameter change derived from completed immutable confirmation evidence.

### 2026-08-25 — Separate order proof from market calibration context

- **Context:** a bounded Mainnet batch cannot also provide two days of public market coverage.
- **Decision:** fingerprint order sessions and read-only calibration archives as separate, disjoint cohorts.
- **Why it worked:** tests preserve ten-order identity while accepting independent multi-day volatility context.
- **Reuse:** every empirical proof that combines paid mutations with broader public observations.

### 2026-08-25 — Validate evidence semantics before worker launch

- **Context:** a late classifier check could detect incompatible evidence only after worker creation.
- **Decision:** validate the complete classifier contract before every SOL worker launch.
- **Why it worked:** tests reject forced modes and changed confirmations before the mutation boundary.
- **Reuse:** every evidence-bound execution policy with configurable runtime inputs.

### 2026-08-24 — Distinguish cold-start evidence sources

- **Context:** compatible history can be unavailable while live independent training continues normally.
- **Decision:** report closed-history and live cold-start counts separately against one immutable training requirement.
- **Why it worked:** the dashboard exposes real progress without admitting incompatible older strategy evidence.
- **Reuse:** every statistical cold-start that can combine archived and newly collected evidence.

### 2026-08-24 — Use one aggregate-trade selector family per page

- **Context:** Binance rejects continuation identifiers combined with time-range parameters.
- **Decision:** bound the first page by time, then continue only by aggregate-trade identifier.
- **Why it worked:** tests prove valid parameters, contiguous identities, bounded completion, and secret-safe diagnostics.
- **Reuse:** every remote pagination API with mutually exclusive cursor and range selectors.

### 2026-08-22 — Keep SHADOW evidence independent from execution plan validity

- **Context:** high volatility made an adaptive profit floor exceed the configured TP ceiling and stopped immutable evidence.
- **Decision:** clamp only the observational baseline to the TP ceiling. Keep execution on the default fail-closed path.
- **Why it worked:** tests prove SHADOW returns the ceiling and LIVE execution rejects identical inputs.
- **Reuse:** every immutable observer that shares calculations with an execution planner.

### 2026-08-22 — Reclaim external backup capacity before mirroring

- **Context:** post-copy retention cannot recover a full external backup disk.
- **Decision:** apply external retention before copying and preserve the newest encrypted archive.
- **Why it worked:** expired files free capacity without removing the latest recovery point.
- **Reuse:** every capacity-sensitive write to a bounded external store.

### 2026-08-21 — Lock every audited bootstrap distribution

- **Context:** dependency auditing inspected a runner-provided tool outside the project lock policy.
- **Decision:** pin `pip` inside the hash-locked audit environment before the audit starts.
- **Why it worked:** local and GitHub audits inspect the same safe tool version.
- **Reuse:** every isolated verification environment that audits its own package manager or bootstrap tools.

### 2026-08-21 — Separate terminal gaps from mutable evidence

- **Context:** a stable evidence prefix stopped at an immutable snapshot without an outcome value.
- **Decision:** skip only known terminal gaps after their cutoff and retain pending or unknown rows as blockers.
- **Why it worked:** tests preserve later resolved evidence, time cutoffs, and fail-closed handling for unknown reasons.
- **Reuse:** every chronological evidence reader that combines terminal gaps with retriable work.

### 2026-08-20 — Persist only aggregate star snapshots

- **Context:** GitHub restricted user-level Stargazer lists and the hourly Pages workflow failed continuously.
- **Decision:** read repository counts, merge bounded daily snapshots, and retain one public seed without account identities.
- **Why it worked:** tests cover removals, same-day events, corrupt state, response limits, and current public metadata.
- **Reuse:** every public trend artifact that needs aggregate history but does not need user-level records.

### 2026-08-19 — Resolve activation HALT from Risk Manager

- **Context:** a caller-selected file could satisfy the CHAMPION activation check without the authoritative HALT.
- **Decision:** resolve and validate the configured HALT while holding the Risk Manager lock through activation.
- **Why it worked:** tests reject missing, malformed, and caller-selected evidence and serialize a concurrent reset.
- **Reuse:** every privileged mutation that requires an existing persistent safety state.

### 2026-08-18 — Version report semantics with each experiment generation

- **Context:** a current report also renders superseded generations with older training boundaries.
- **Decision:** apply powered historical training only to generations that preregister that design.
- **Why it worked:** old reports retain their original cohort rules and cannot block current collection.
- **Reuse:** every dashboard that recomputes immutable generations under evolving statistical code.

### 2026-08-18 — Size experiments before evidence collection

- **Context:** fixed sample counts and rare PANIC observations made canary duration unclear.
- **Decision:** use exact power analysis, closed-history training, live confirmation, and separate 45-day phase deadlines.
- **Why it worked:** each cohort has a preregistered size, purpose, deadline, and independent evidence boundary.
- **Reuse:** every time-series experiment with expensive independent observations and rare safety states.

### 2026-08-18 — Bind promotion to executable policy

- **Context:** statistical confirmation did not prove that a worker used the selected policy.
- **Decision:** block promotion with `EXECUTION_POLICY_NOT_BOUND` until startup verifies every frozen parameter.
- **Why it worked:** a confirmed experiment cannot authorize different execution semantics.
- **Reuse:** every evidence gate that enables an execution-changing feature.

### 2026-08-18 — Version control evidence by model semantics

- **Context:** short horizons and weak metadata validation could misstate control effectiveness.
- **Decision:** start V4 journals with control-specific horizons and authoritative plan fingerprints.
- **Why it worked:** old evidence cannot mix with the stricter preregistered model.
- **Reuse:** every statistical model change that alters cohorts, horizons, or normalization.

### 2026-08-18 — Preserve interactive state across polling redraws

- **Context:** a dashboard refresh replaced open nested history panels every five seconds.
- **Decision:** capture stable open panel keys before replacement and restore them in the new markup.
- **Why it worked:** browser verification keeps the selected panel open after a complete section redraw.
- **Reuse:** every polled view that replaces interactive HTML elements.

### 2026-08-18 — Use one evaluation cohort for all selection tests

- **Context:** configuration Holm tests included cold-start rows that the walk-forward gate excluded.
- **Decision:** derive one post-training cohort and use it for the gate, configuration test, and Holm correction.
- **Why it worked:** training outcomes cannot change selection p-values, while evaluation outcomes remain unchanged.
- **Reuse:** every model-selection process that separates training data from evaluation data.

### 2026-08-18 — Require stateful evidence for stateful controls

- **Context:** independent order outcomes could not represent inventory feedback across later decisions.
- **Decision:** block inventory promotion until a sequential portfolio replay models exposure, CAP use, and later order sizes.
- **Why it worked:** inventory reports remain observable but cannot claim an unsupported APPLY result.
- **Reuse:** every policy where one action changes the state used by later actions.

### 2026-08-18 — Version and validate control evidence semantics

- **Context:** permissive metadata truthiness could misclassify damaged rows as binding evidence.
- **Decision:** start version-three cohorts with strict identity, type, transition, applicability, and notional validation.
- **Why it worked:** malformed metadata blocks the gate, and observation-only inventory is explicitly not applicable.
- **Reuse:** every append-only evidence stream whose metadata selects a statistical cohort.

### 2026-08-17 — Define independence by complete outcome intervals

- **Context:** five-minute snapshots shared most of their 300-minute and 360-minute outcome periods.
- **Decision:** retain raw rows, but infer only from starts separated beyond the longest inclusive outcome interval.
- **Why it worked:** reports show raw and purged counts, while confirmation blocks contain no overlapping outcomes.
- **Reuse:** every experiment where labels remain dependent after grouping multiple horizons by snapshot.

### 2026-08-17 — Keep absolute inventory limits outside adaptive controls

- **Context:** the managed-inventory CAP was evaluated inside an optional inventory-skew mode.
- **Decision:** enforce one explicit absolute CAP per execution symbol in the Risk Manager.
- **Why it worked:** missing or reached CAPs block BUY in every adaptive-control mode.
- **Reuse:** every safety limit that must remain active when an optimization feature is observational.

### 2026-08-17 — Require one evidence gate per strategy control

- **Context:** one generic strategy gate authorized four controls with different decision semantics.
- **Decision:** record and approve expectancy, inventory, maker, and regime counterfactuals separately.
- **Why it worked:** one control's evidence or approval cannot authorize another control.
- **Reuse:** every independently switchable control that can change execution behavior.

### 2026-08-17 — Narrow ETH gaps around the participation boundary

- **Context:** version twelve found negative expectancy at 19 basis points and insufficient fills at 27 basis points.
- **Decision:** keep 22 basis points as control and test 20 and 21 basis points.
- **Why it worked:** tests change only the entry gap and preserve the lifetime, horizons, maker policy, and SHADOW isolation.
- **Reuse:** every generation where adjacent candidates bound participation and expectancy in opposite directions.

### 2026-08-16 — Let measured equity advance the risk day

- **Context:** control actions had no current equity but could initialize a new daily baseline.
- **Decision:** only an authoritative risk snapshot can advance the equity day.
- **Why it worked:** tests preserve prior equity through control actions and reset it on the next snapshot.
- **Reuse:** every financial state transition that also has a non-financial control path.

### 2026-08-16 — Derive symbol-scoped evidence after validation

- **Context:** the Pi harness combined a variable symbol with a fixed SOL User Stream path.
- **Decision:** derive the default evidence path from the validated symbol and preserve explicit overrides.
- **Why it worked:** tests select ETH evidence by default and retain one reviewed custom path.
- **Reuse:** every CLI where one selector determines a default evidence artifact.

### 2026-08-16 — Audit all active financial boundaries explicitly

- **Context:** the numeric audit omitted active risk and exact-accounting modules.
- **Decision:** register each critical module with its reviewed current direct-float ceiling.
- **Why it worked:** tests verify zero and compatibility ceilings for risk and accounting paths.
- **Reuse:** every financial module added outside an existing audited package.

### 2026-08-16 — Retry complete report pages without partial output

- **Context:** one temporary network failure stopped paginated trade history with a raw traceback.
- **Decision:** retry each complete page within a fixed limit and block the report after exhaustion.
- **Why it worked:** tests recover one failed page and reject persistent failure without partial output.
- **Reuse:** every bounded report that reads paginated remote evidence.

### 2026-08-16 — Publish observations instead of constant proof claims

- **Context:** one status field claimed an unchanged execution scope with a constant Boolean value.
- **Decision:** publish the execution, analysis, and SHADOW-only symbol lists without a proof flag.
- **Why it worked:** the versioned status now contains only values derived from its inputs.
- **Reuse:** every operational status that describes a safety boundary enforced elsewhere.

### 2026-08-16 — Verify protection by structure and quantity

- **Context:** an account-wide OCO leg count could hide one uncovered position remainder.
- **Decision:** require two equal legs for each OCO and compare covered quantity with account quantity.
- **Why it worked:** tests detect an uncovered third position behind two complete OCO lists.
- **Reuse:** every portfolio check that aggregates exchange-side position protection.

### 2026-08-16 — Preserve long soak progress through source failures

- **Context:** one temporary source failure could end a twelve-hour Testnet soak without a report.
- **Decision:** checkpoint the report, retry within a fixed limit, and block persistent source failure.
- **Why it worked:** tests preserve completed samples, reject persistent failure, and exclude provider response text.
- **Reuse:** every long verification loop that depends on a remote data source.

### 2026-08-16 — Parse financial symbols through one canonical boundary

- **Context:** one PnL tool copied an incomplete quote list and guessed every unknown quote as four characters.
- **Decision:** expose one fail-closed base and quote parser from execution accounting.
- **Why it worked:** tests classify TRY, GBP, and AUD correctly and reject an unknown quote before a signed request.
- **Reuse:** every financial reader that derives assets from a Binance symbol.

### 2026-08-16 — Change one experiment axis at a time

- **Context:** deeper SOLUSDT gaps improved expectancy but reduced the fill rate to zero.
- **Decision:** hold the 48 basis-point gap and compare 60-minute, 75-minute, and 90-minute lifetimes.
- **Why it worked:** tests keep every other candidate parameter equal and identify lifetime as the only changed axis.
- **Reuse:** every experiment where evidence supports one parameter but another parameter limits participation.

### 2026-08-16 — Calibrate BTC gaps from completed selection windows

- **Context:** BTCUSDT version eleven produced no fills at 38, 42, or 44 basis points.
- **Decision:** select version-twelve gaps from completed 60-minute SELECTION excursions before a fixed cutoff.
- **Evidence:** 188 complete windows ended by 2026-08-16 06:27:02 UTC.
- **Why it worked:** 8.4, 9.4, and 10.3 basis points produced touch rates of 14.89%, 9.04%, and 4.79%.
- **Reuse:** every zero-fill symbol that requires evidence-based entry recalibration.

### 2026-08-15 — Keep external AI inside execution scope

- **Context:** observation-only symbols consumed most of the daily external AI budget.
- **Decision:** run external advice only for execution symbols, while all symbols retain statistical SHADOW collection.
- **Why it worked:** scope tests preserve ETH and BTC evidence without external advisor requests.
- **Reuse:** every research scope that is broader than the approved execution scope.

### 2026-08-15 — Prefer direct account valuation quotes

- **Context:** an account asset had a direct USDT pair but valuation started with less reliable bridge pairs.
- **Decision:** fetch and cache the direct USDT quote before any bridge conversion.
- **Why it worked:** tests resolve KERNEL through `KERNELUSDT` and preserve the fail-closed bridge fallback.
- **Reuse:** every exact account valuation path with direct and bridged market pairs.

### 2026-08-15 — Keep scenario analysis independent from execution scope

- **Context:** long-horizon evidence needs several symbols without enabling new workers.
- **Decision:** configure analysis symbols separately and collect public closed candles in a credential-free SHADOW service.
- **Why it worked:** tests prove identical rules, symbol-specific statistics, exact-next-candle settlement, and no order imports.
- **Reuse:** every research feed that needs broader market coverage than the approved execution scope.

Read this file before changing the repository. Record only decisions that were
validated by tests or production evidence and are likely to be reused. Keep
entries concise; this is not a changelog or an activity log.

### 2026-08-14 — Keep remote valuation outside local accounting requests

- **Context:** sequential Binance reads exceeded the dashboard deadline and hid complete local trade totals.
- **Decision:** return local accounting immediately and refresh one bounded, disposable valuation cache in the background.
- **Why it worked:** tests return partial data immediately, reuse stale data, and cap cache growth at 16 entries.
- **Reuse:** every dashboard endpoint that combines local authoritative data with slower external telemetry.

### 2026-08-14 — Size client deadlines from production latency

- **Context:** valid dashboard responses completed after the previous client deadline during concurrent refreshes.
- **Decision:** use a bounded 20-second deadline and preserve each failed section name through concurrent collection.
- **Why it worked:** production responses completed within 14 seconds, and focused transport tests pass.
- **Reuse:** every operational client that polls several independent sources concurrently.

### 2026-08-14 — Keep prediction and execution symbol scopes separate

- **Context:** ETH prediction evidence was needed without enabling an ETH worker.
- **Decision:** configure prediction symbols separately and force additional symbols through the read-only collector.
- **Why it worked:** tests preserve the execution list and pass ETH with `execution_allowed=False`.
- **Reuse:** every multi-symbol experiment that is not approved for execution.

### 2026-08-14 — Start regime holds at process creation

- **Context:** one regime classifier treated the first transition as if the prior state began at the Unix epoch.
- **Decision:** initialize each regime hold from the monotonic process clock and apply it to the first transition.
- **Why it worked:** boundary tests block the first transition before 300 seconds and allow it at 300 seconds.
- **Reuse:** every state machine that limits transition frequency after process start.

### 2026-08-13 — Count only accepted flatten submissions

- **Context:** emergency flatten loops reduced their local remainder after rejected LIMIT and MARKET orders.
- **Decision:** reduce the remainder only after an accepted order and keep stalled modes BUY-blocking.
- **Why it worked:** regressions prove rejection cannot report progress or increase a SELL above the available remainder.
- **Reuse:** every order loop that derives local progress from an exchange mutation.

### 2026-08-13 — Use Wilder smoothing for ATR

- **Context:** the worker PANIC indicator used the standard EMA weight for Average True Range.
- **Decision:** seed ATR with one period average, then apply Wilder smoothing to each closed candle.
- **Why it worked:** a deterministic candle sequence produces the canonical value and ignores the open candle.
- **Reuse:** every risk threshold that names a standard technical indicator.

### 2026-08-13 — Resolve frozen parameters from configuration

- **Context:** a selection preview reconstructed the configured entry gap from one stored market price and plan.
- **Decision:** resolve each current-generation gap from the same immutable table that builds its SHADOW variant.
- **Why it worked:** two rounded plans at different prices now produce the same preview gap and fingerprint semantics.
- **Reuse:** every operator workflow that reconstructs immutable strategy parameters from stored evidence.

### 2026-08-13 — Observe recovery before rejecting a maker entry

- **Context:** version-ten fills remained negative at 120 minutes but recovered near the active gap boundary after 300 minutes.
- **Decision:** version-eleven tests 38, 42, and 44 basis points with 300-minute and 360-minute outcomes.
- **Why it worked:** bounded production replay retained useful fills and produced positive mean PnL at both new horizons.
- **Reuse:** every experiment where the entry lifetime and expected recovery exceed the original outcome horizon.

### 2026-08-13 — Reconstruct fingerprints from frozen semantics

- **Context:** the current ticker and closed-bar feature price can differ for one confirmation decision.
- **Decision:** reconstruct stable rules from the immutable manifest and validate each stored plan separately.
- **Why it worked:** a regression changes the construction price while the frozen rule fingerprint remains valid.
- **Reuse:** every integrity check that reconstructs snapshot-independent configuration from dynamic evidence.

### 2026-08-13 — Bind aggregate denominators to the evaluated cohort

- **Context:** confirmation reports retain complete windows beyond the predeclared evaluation prefix.
- **Decision:** calculate each summary numerator and denominator from the same frozen window prefix.
- **Why it worked:** a regression adds an adverse later window and proves that frozen summary metrics do not change.
- **Reuse:** every report that retains evidence beyond a predeclared evaluation cohort.

### 2026-08-12 — Test the observed participation boundary

- **Context:** version-seven filled at 35 basis points, while versions four and eight had no fills at 40 basis points.
- **Decision:** version-nine tests 34, 36, and 38 basis points with the corrected lifetime and outcome windows.
- **Why it worked:** production history defines the narrow boundary, and tests prove distinct immutable SHADOW plans.
- **Reuse:** every experiment where adjacent generations identify active and inactive parameter regions.

### 2026-08-12 — Separate auth probing from operator reminder cadence

- **Context:** signed access must retry quickly, but repeated Telegram notices do not improve recovery.
- **Decision:** retry signed checks each minute and repeat one operator-focused incident notice after four hours.
- **Why it worked:** tests preserve failed-delivery retry while suppressing endpoint changes and 30-minute reminders.
- **Reuse:** every persistent external authorization incident with automatic recovery probes.

### 2026-08-11 — Require positive absolute expectancy after relative improvement

- **Context:** version-seven beat its baseline but retained a negative net expectancy confidence interval at every tested gap.
- **Decision:** version-eight tests deeper maker entries and keeps the corrected lifetime and outcome windows.
- **Why it worked:** production evidence separates improved relative edge from an economically acceptable absolute result.
- **Reuse:** every experiment where a candidate can beat a losing baseline while remaining unprofitable.

### 2026-08-11 — Alert on persisted incident transitions

- **Context:** one changed public IP remained pending through each signed authentication retry.
- **Decision:** alert only when the persisted pending fingerprint changes, and omit diagnostic identifiers from Telegram.
- **Why it worked:** tests prove repeated observations send one notice and signed recovery accepts the pending fingerprint before its notice.
- **Reuse:** every persistent incident whose condition remains true across retries or process restarts.

### 2026-08-10 — Observe an exit after the entry lifetime

- **Context:** version-six ended one outcome horizon when its 60-minute BUY lifetime ended.
- **Decision:** version-seven uses a 60-minute entry lifetime with 90-minute and 120-minute outcomes.
- **Why it worked:** a regression fills at minute 60 and observes a later TP on both horizons.
- **Reuse:** every experiment where entry can occur near the end of its permitted lifetime.

### 2026-08-08 — Tune entry distance and lifetime as one SHADOW matrix

- **Context:** deeper maker entry improved edge and drawdown but reduced fill rate.
- **Decision:** compare three deep gaps with two longer lifetimes in global and RANGE-only scopes.
- **Why it worked:** tests prove twelve immutable kinds, equal snapshots, exact TP reuse, and permanent SHADOW isolation.
- **Reuse:** every experiment where one safer parameter creates a measurable participation tradeoff.

### 2026-08-08 — Keep the socket peer authoritative until application authentication

- **Context:** automatic proxy parsing changed the peer before application checks.
- **Decision:** disable Uvicorn proxy parsing and accept one client header after local proxy authentication.
- **Why it worked:** tests reject remote proxy claims and preserve independent client rate buckets.
- **Reuse:** every local reverse proxy that supplies security-sensitive client identity.

### 2026-08-08 — Reject every top-level transaction terminator

- **Context:** SQLite accepts standalone `END` as an alias for `COMMIT`.
- **Decision:** reject `END` and `END TRANSACTION` when either starts a migration statement.
- **Why it worked:** regression tests prove rejection occurs before schema mutation and triggers remain valid.
- **Reuse:** every parser that executes scripts inside a caller-owned transaction.

### 2026-08-08 — Validate economic plans before external actions

- **Context:** a malformed ladder could select hidden defaults after market reads.
- **Decision:** parse and validate the complete plan before network access or worker launch.
- **Why it worked:** tests prove invalid LIVE input causes no API request and no child process.
- **Reuse:** every operator command that converts text into execution parameters.

### 2026-08-08 — Expose blocked scheduled maintenance to systemd

- **Context:** a safety block can prevent retention without changing protected data.
- **Decision:** use success only for completed or empty work; preserve a nonzero BLOCKED exit.
- **Why it worked:** tests distinguish an empty PASS from a backup-gated BLOCKED result.
- **Reuse:** every scheduled maintenance job with a fail-closed status.

### 2026-08-08 — Require complete exchange fill identity

- **Context:** AI fill deduplication needs the Binance order and trade identifiers.
- **Decision:** reject partial identities before any ledger or AI database mutation.
- **Why it worked:** tests prove fail-closed rejection, restart idempotency, and payload-safe diagnostics.
- **Reuse:** every financial event whose external identity controls deduplication.

### 2026-08-05 — Start alert cooldowns after confirmed delivery

- **Context:** a failed Telegram request could suppress later authentication alerts.
- **Decision:** record the delivery result and use a short retry delay after failure.
- **Why it worked:** tests prove endpoint deduplication, failed-delivery retry, and systemd configuration injection.
- **Reuse:** every alert where transport success controls the next delivery interval.

### 2026-08-05 — Narrow experiments around the least harmful boundary

- **Context:** closer BUY prices increased fills but made every version-two net confidence interval negative.
- **Decision:** test nine maker-only variants that keep or deepen the baseline BUY and use one authoritative TP floor.
- **Why it worked:** tests prove equal snapshots, new identifiers, strict SHADOW isolation, and no closer BUY price.
- **Reuse:** every experiment generation after broad parameter exploration rejects the tested direction.

### 2026-08-05 — Start a new soak epoch only after causal repair

- **Context:** authentication failure produced reconnect churn that could not represent repaired transport stability.
- **Decision:** preserve failed epochs, then start a new baseline after fresh signed authentication and IP Guard recovery.
- **Why it worked:** v3 migration tests retain v1 and v2 evidence and use exact lifetime counters.
- **Reuse:** every repeated certification after a verified external dependency repair.

### 2026-08-05 — Drive operational notices from fresh runtime state

- **Context:** an authentication warning depended on one deployment record and one narrower runtime state.
- **Decision:** select the notice from a fresh fail-closed heartbeat, independently of deployment history.
- **Why it worked:** tests cover distinct authentication and changed-IP messages and reject stale heartbeats.
- **Reuse:** every dashboard warning for a live runtime condition.

### 2026-08-04 — Use cooldowns for persistent incident reminders

- **Context:** one recovery latch also suppressed every later alert for an unresolved bot failure.
- **Decision:** send each confirmed failure through the shared cooldown gate; use the latch only for recovery hysteresis.
- **Why it worked:** tests suppress an immediate duplicate and send another alert after the exact cooldown.
- **Reuse:** every persistent incident that needs bounded reminders and a separate recovery message.

### 2026-08-03 — Test network reachability instead of packet idleness

- **Context:** a five-second interface check treated normal traffic gaps as Wi-Fi failures.
- **Decision:** keep the hardware watchdog, but assign network checks to the hysteresis watchdog.
- **Why it worked:** live evidence showed a healthy route and fresh transport activity during repeated warnings.
- **Reuse:** every watchdog that observes an interface with bursty traffic.

### 2026-08-03 — Retire only identified legacy deployment units

- **Context:** an obsolete timer repeatedly called a script removed from the current release.
- **Decision:** verify the legacy command and timer target before unit removal.
- **Why it worked:** tests prove that retirement stops before deletion when a same-name unit differs.
- **Reuse:** every deployment cleanup that removes root-owned services from an earlier architecture.

### 2026-08-03 — Apply venue paths as one validated set

- **Context:** optional Testnet overrides could leave Mainnet state paths active.
- **Decision:** resolve every Testnet path, prove separation, then replace the complete environment set.
- **Why it worked:** tests prove safe defaults, explicit paths, collision rejection, and no partial mutation.
- **Reuse:** every environment switch that selects persistent state or control evidence.

### 2026-08-03 — Share symbol quote vocabulary with exact accounting

- **Context:** a fixed four-character fallback corrupted assets for BTC, ETH, and BNB quotes.
- **Decision:** infer only from the accounting quote list and reject unknown suffixes.
- **Why it worked:** tests cover three-, four-, and five-character quotes plus fail-closed rejection.
- **Reuse:** every offline or read-only parser for Binance concatenated symbols.

### 2026-08-03 — Do not stream data without an active consumer

- **Context:** fast-market candles produced unseeded indicators that no decision or report consumed.
- **Decision:** remove the stream and fields; test any adaptive threshold in SHADOW before integration.
- **Why it worked:** tests prove the reduced stream still supplies every fast-market gate input.
- **Reuse:** every subscription, cache, and derived metric without a named consumer.

### 2026-08-03 — Reset connection-scoped market evidence on reconnect

- **Context:** full depth snapshots can repeat identifiers, and identifiers do not span WebSocket sessions.
- **Decision:** accept duplicate snapshots and clear identifiers and freshness before each new session.
- **Why it worked:** tests prove transient blocking, recovery, and fresh-frame requirements after reconnect.
- **Reuse:** every stream where sequence identity or freshness belongs to one connection.

### 2026-08-03 — Reject unsorted evidence instead of repairing it silently

- **Context:** OHLC open and close depend on authenticated trade chronology.
- **Decision:** require nondecreasing timestamps while streaming verified archives.
- **Why it worked:** tests identify the first reversed trade before bar construction completes.
- **Reuse:** every financial adapter where source order defines an aggregate value.

### 2026-08-03 — Buffer independent events until synchronization is proved

- **Context:** trades could arrive before the depth stream completed its sequence handshake.
- **Decision:** retain them in a bounded buffer and publish only after contiguous depth evidence.
- **Why it worked:** tests preserve early trades and reject capacity exhaustion without partial files.
- **Reuse:** every recorder that combines independently ordered streams behind one synchronization gate.

### 2026-08-03 — Aggregate evidence only by unique authoritative identity

- **Context:** repeated validation files could count one archive more than once.
- **Decision:** block duplicate archive identities and keep conservative diagnostic totals.
- **Why it worked:** tests prove repeated reports cannot increase validated-order evidence.
- **Reuse:** every readiness gate that aggregates reports, samples, or lifecycle evidence.

### 2026-08-03 — Own financial provenance vocabulary at the accounting boundary

- **Context:** independent status allowlists excluded different valued commissions.
- **Decision:** exact accounting owns one status predicate for all financial consumers.
- **Why it worked:** tests accept legacy evidence and reject unknown provenance across accounting and replay calibration.
- **Reuse:** every report, model, or gate that consumes commission values.

### 2026-08-02 — Keep partial risk uncertainty inside a valid snapshot

- **Context:** one unknown FIFO loss streak suppressed reconciliation and SHADOW evidence.
- **Decision:** publish the unknown field and block BUY at the Risk Manager boundary.
- **Why it worked:** tests preserve a valid snapshot while unknown provenance blocks exposure.
- **Reuse:** every independent risk metric that can be unavailable without invalidating other evidence.

### 2026-08-02 — Publish safety evidence at its authoritative source

- **Context:** Pi verification read reconciliation evidence that only the dashboard derived from text.
- **Decision:** publish structured evidence from the supervisor and reject missing evidence at every safety consumer.
- **Why it worked:** tests distinguish a proved match, a mismatch, and unavailable evidence.
- **Reuse:** every release gate that consumes runtime safety state.

### 2026-08-02 — Bind CI exceptions to authoritative event evidence

- **Context:** commit topology alone cannot prove that a merge came from GitHub pull request CI.
- **Decision:** require the exact workflow event, merge ref, merge SHA, two parents, and event head before allowing a parent version commit.
- **Why it worked:** tests accept one verified synthetic merge and reject local, octopus, wrong-head, and base-version merges.
- **Reuse:** every verification exception that depends on CI provider identity or event topology.

### 2026-08-02 — Use one FIFO sign for risk and reporting

- **Context:** average cost and FIFO can assign opposite signs to one ladder SELL.
- **Decision:** derive risk streaks from the canonical FIFO allocator and retain only active derived lots.
- **Why it worked:** tests prove FIFO loss detection, scoped incomplete history, bounded outcomes, and exact import synchronization.
- **Reuse:** every gate or report that classifies an individual SELL as profit or loss.

### 2026-08-02 — Isolate each sequential model process

- **Context:** mixed symbols and horizons created transitions between different processes at one market time.
- **Decision:** fit and update each HMM by symbol and horizon; score models only on trained sequences.
- **Why it worked:** tests prove separate transitions, independent prior state, and equal exclusion of cold sequences.
- **Reuse:** every sequential model over multi-symbol or multi-horizon evidence.

### 2026-08-02 — Compare predictors on one availability cohort

- **Context:** per-source filters let intermittent predictors select different observations and bias accuracy.
- **Decision:** score all sources only where every source predicted; report total, common, and per-source availability.
- **Why it worked:** tests prove missing and future predictions cannot alter the common comparison.
- **Reuse:** every side-by-side model report with optional or intermittent prediction sources.

### 2026-08-02 — Keep named financial methods in one canonical module

- **Context:** dashboard FIFO logic used float arithmetic and rejected a commission status accepted by exact accounting.
- **Decision:** implement FIFO once with Decimal and keep dashboard code as a read-only presentation adapter.
- **Why it worked:** tests prove exact legacy fees, FIFO lot order, window replay, and fail-closed incomplete history.
- **Reuse:** every report or user interface that presents an accounting result already defined by the execution layer.

### 2026-08-02 — Finalize verified OTOCO state through one boundary

- **Context:** normal success and lost-ACK recovery proved the same exchange state through separate journal paths.
- **Decision:** use one finalizer that records structure and promotes fully active protection to `PROTECTED`.
- **Why it worked:** regressions prove lost-ACK recovery protects both intents, while definitive rejection fails both prepared intents.
- **Reuse:** every mutation whose normal and reconciled outcomes can prove the same durable lifecycle state.

### 2026-08-02 — Normalize ranked prices after transformation

- **Context:** a unique sorted ladder can receive later price transformations.
- **Decision:** repeat uniqueness and ordering normalization before rank-based order matching.
- **Why it worked:** tests prove market-gap adjustment preserves two distinct descending target ranks.
- **Reuse:** every ranked price plan that transforms values after its initial deduplication.

### 2026-08-02 — Require exact time identity for financial evidence

- **Context:** an API can return the first record after a requested time.
- **Decision:** compare the returned timestamp with the requested timestamp before calculation or caching.
- **Why it worked:** tests reject later candles, preserve an empty cache, and accept an exact inverse conversion.
- **Reuse:** every historical fee, price, rate, candle, or external value joined by time.

### 2026-08-02 — Verify protection on both sides of replacement

- **Context:** a breakeven move removes one OCO before it creates another OCO.
- **Decision:** verify old-list absence, then require a verified replacement or create HALT.
- **Why it worked:** tests cover delayed cancellation, empty responses, network errors, successful re-arm, and secret-safe diagnostics.
- **Reuse:** every workflow that replaces exchange-side protection after a destructive mutation.

### 2026-08-02 — Validate exchange filters before rounding

- **Context:** a missing filter became zero and silently disabled step rounding.
- **Decision:** require finite positive filter values in parsing, normalization, rounding, and formatting boundaries.
- **Why it worked:** regressions reject missing and invalid filters before caching or order submission.
- **Reuse:** every exchange adapter that converts venue metadata into executable order parameters.

### 2026-08-02 — Convert Retry-After into a non-blocking local cooldown

- **Context:** immediate public-read retries can extend an exchange rate limit or IP ban.
- **Decision:** cache one bounded error until `Retry-After` expires and make no network request during that interval.
- **Why it worked:** tests prove one exchange call, no blocking sleep, exact cooldown expiry, bounded defaults, and query-free diagnostics.
- **Reuse:** every read-only transport used by latency-sensitive or periodic services.

### 2026-08-02 — Adapt VWAP discount in its conservative direction

- **Context:** a static discount made its bounds, smoothing, and persistent state ineffective.
- **Decision:** increase the threshold for DOWN, loss, and volatility evidence; decrease it for UP and profit evidence.
- **Why it worked:** exact tests prove bounded Decimal changes, sample gating, invalid-input rejection, and active-interpreter execution.
- **Reuse:** every threshold where a larger value requires stronger evidence before exposure can increase.

### 2026-08-02 — Version changed experiment semantics

- **Context:** a changed plan under an existing kind would mix incompatible SHADOW outcomes.
- **Decision:** assign new kinds to changed candidates and retain old terminal evidence unchanged.
- **Why it worked:** tests prove one snapshot contains only the new matrix and each kind has explicit baseline evidence.
- **Reuse:** every experiment whose price, lifetime, execution policy, feature formula, or regime rule changes.

### 2026-08-01 — Preserve unattributable fill evidence

- **Context:** historical canary fills had journal proof but no valid `decision_id`.
- **Decision:** review an exact bounded set, preserve each row, and never invent an AI link.
- **Why it worked:** tests prove pending gates clear while RAG and AI fills remain unchanged.
- **Reuse:** every historical execution fact that cannot receive exact model attribution.

### 2026-08-01 — Deduplicate alerts by stable cause

- **Context:** retry counters made one persistent risk failure look new each cycle.
- **Decision:** keep counters in status, but exclude them from the alert identity.
- **Why it worked:** tests prove changed causes alert immediately while repeated causes stay stable.
- **Reuse:** every alert that contains attempts, ages, timestamps, or other volatile diagnostics.

### 2026-08-01 — Isolate static analysis from application credentials

- **Context:** a verification child does not need exchange or notification credentials.
- **Decision:** run Semgrep with a minimal environment and project-local writable directories.
- **Why it worked:** tests prove application secrets are absent while pinned offline scans pass.
- **Reuse:** every development tool that analyzes source without runtime authority.

### 2026-08-01 — Refresh IP evidence at every authentication boundary

- **Context:** a public IP can change after startup during a long supervisor run.
- **Decision:** refresh two-source fingerprint evidence before runtime authentication backoff.
- **Why it worked:** tests prove runtime rejection observes before persistence, while non-LIVE modes make no IP request.
- **Reuse:** every long-running authenticated service with network-identity diagnostics.

### 2026-08-01 — Reject a complete malformed financial map

- **Context:** skipping one invalid item can silently remove its position limit.
- **Decision:** reject malformed, duplicate, negative, or unconfigured map items before preflight.
- **Why it worked:** exact Decimal tests prove one bad item prevents every partial result.
- **Reuse:** every configuration map that controls money, quantity, exposure, or loss.

### 2026-08-01 — Accept changed IP only after current authoritative evidence

- **Context:** manual acceptance remained necessary after an operator updated the Binance whitelist.
- **Decision:** require fresh two-source consensus and a complete signed read-only preflight before automatic acceptance.
- **Why it worked:** tests prove retries preserve pending state and stale consensus cannot authorize acceptance.
- **Reuse:** every automatic recovery that changes a persisted trust baseline.

### 2026-08-01 — Serialize control state and bound loss-streak reads

- **Context:** three processes can change HALT state while risk checks read trade history.
- **Decision:** lock each control transition and maintain 4,096 derived SELL outcomes.
- **Why it worked:** tests prove process exclusion, transactional updates, exact backfill, and fixed growth.
- **Reuse:** every shared control file and every risk metric derived from growing authoritative history.

### 2026-08-01 — Publish deployment facts only after readiness passes

- **Context:** an IP whitelist block can hide successful local dashboard recovery.
- **Decision:** publish one bounded deployment record after heartbeat, API, and SQLite checks pass.
- **Why it worked:** tests prove ordering, validation, dashboard isolation, and an English Telegram message without an IP address.
- **Reuse:** every operator message that combines deployment success with an independent fail-closed trading state.

### 2026-08-01 — Separate exposure from acquired inventory

- **Context:** a partial BUY fill exists in account holdings while its remainder stays in the order book.
- **Decision:** value holdings once and add only each open BUY remainder to risk exposure.
- **Why it worked:** exact regressions prove partial quantity is not duplicated across portfolio, symbol, or correlated exposure.
- **Reuse:** every risk calculation that combines settled balances with partially executed orders.

### 2026-08-01 — Classify deterministic risk blocks separately

- **Context:** missing configured VaR history cannot recover through API retry or cooldown.
- **Decision:** block BUY with configuration telemetry and preserve the current API failure count.
- **Why it worked:** regressions prove configuration errors bypass API counting and API cooldown paths.
- **Reuse:** every fail-closed condition caused by configuration or required local evidence.

### 2026-08-01 — Read stop state at every exchange boundary

- **Context:** a copied Boolean cannot observe a signal that arrives during a multi-order batch.
- **Decision:** read mutable worker state before each balance read and order request; import stable dependencies directly.
- **Why it worked:** regressions prove BUY placement has no captured `RUN` snapshot and the worker monolith does not grow.
- **Reuse:** every long-running function that can cross a mutation boundary after shutdown starts.

### 2026-08-01 — Archive derived telemetry before bounded retention

- **Context:** continuous SHADOW evidence grows much faster than accounting and recovery databases.
- **Decision:** keep authoritative data indefinitely; archive only terminal derived rows after a recent encrypted backup.
- **Why it worked:** tests prove pending rows survive, stale backup evidence blocks deletion, and archived counts match deleted counts.
- **Reuse:** every persistent telemetry feature that can grow for the life of the service.

### 2026-08-01 — Persist definitive recovery conflicts, not transient reads

- **Context:** startup recovery must distinguish an uncertain exchange read from a proven journal conflict.
- **Decision:** retry transient reads without HALT; persist HALT for definitive conflicts; archive damaged HALT evidence before replacement.
- **Why it worked:** regressions prove exact error classification, wrapped-cause handling, durable conflict reasons, and preserved damaged evidence.
- **Reuse:** every startup gate that compares durable local state with an external authority.

### 2026-08-01 — Prove stream recovery with bounded Testnet evidence

- **Context:** service restarts do not prove socket reconnect or event-triggered REST behavior.
- **Decision:** force one reconnect, create one bounded Testnet order, and confirm its authenticated event with REST.
- **Why it worked:** tests prove reconnect, event identity, REST authority, confirmation, and cleanup.
- **Reuse:** every notification stream whose readiness depends on a real external event.

### 2026-08-01 — Publish fail-closed readiness before slow startup work

- **Context:** authenticated startup can exceed a deployment readiness timeout.
- **Decision:** publish `RISK_PENDING` before preflight and accept only its fresh, BUY-blocked form as startup readiness.
- **Why it worked:** tests prove publication precedes preflight and intentional stops remain excluded.
- **Reuse:** every service with slow startup work and an external readiness gate.

### 2026-07-31 — Combine event updates with scheduled reconciliation

- **Context:** a daily Star History run stayed stale after a new star.
- **Decision:** process new-star events immediately and reconcile the authoritative count hourly.
- **Why it worked:** the event removes normal delay, while the schedule repairs removals and missed events.
- **Reuse:** derived public artifacts whose source provides incomplete change events.

### 2026-07-31 — Derive documentation contracts from executable interfaces

- **Context:** prose can preserve an obsolete command after a CLI changes.
- **Decision:** compare commands, defaults, services, and modes with their executable definitions.
- **Why it worked:** contract tests now compare current guides with CLI and systemd inventories.
- **Reuse:** every guide that describes a command, configuration value, service, or implemented feature.

### 2026-07-31 — Use one controlled English profile for documentation

- **Context:** long sentences and variable terms made safety instructions hard
  to scan and translate.
- **Decision:** use the project ASD-STE100 profile for English documentation.
  Keep procedures at 20 words and descriptions at 25 words.
- **Why it worked:** one checker now validates all current normative guides
  and has focused regression tests.
- **Reuse:** README files, runbooks, safety policies, release records, agent
  rules, and operator help.

### 2026-07-31 — Separate AI evidence cadence from operator log cadence

- **Context:** repeated low-confidence responses are useful SHADOW evidence but
  printing every one obscures incidents, while a provider outage should not be
  retried forever at its shortest recovery interval.
- **Decision:** retain every bounded usage and decision record, rate-limit only
  identical human diagnostics, sanitize transport errors to class/status and
  exponentially back off consecutive failures until the normal cache ceiling.
- **Why it worked:** regressions prove all low-confidence calls remain in usage
  evidence, duplicate messages are hourly, URLs are absent and valid recovery
  resets provider backoff.
- **Reuse:** advisory or telemetry providers where machine evidence and human
  incident logs require different retention and retry cadences.

### 2026-07-31 — Plot trading turnover independently from PnL

- **Context:** sell volume, cash flow and realized PnL answer different
  questions and cannot represent total exchange activity on one chart.
- **Decision:** chart trailing 24-hour executed BUY plus SELL quote turnover at
  every host sample, aggregate money with `Decimal`, and exclude fills newer
  than the plotted timestamp.
- **Why it worked:** exact-window and API regressions prove both sides are
  counted, the boundary is rolling, future fills do not leak and missing trade
  data degrades only the new series.
- **Reuse:** every operational chart or report that visualizes trading activity
  separately from profitability and account-value change.

### 2026-07-29 — Scope soak failures to the audited runtime window

- **Context:** immutable historical failures remain useful evidence but cannot
  prove that every later continuous run failed the same health condition.
- **Decision:** retain lifetime totals while gating a soak only on expirations
  created since its authoritative runtime start; carried unresolved overdue
  work still blocks regardless of origin.
- **Why it worked:** a historical expiration remains visible without blocking
  a clean run, while current-window expiration and old unresolved work fail.
- **Reuse:** every time-bounded readiness audit over an append-only history.

### 2026-07-29 — Distinguish scheduled work from a processing backlog

- **Context:** continuous multi-horizon prediction always has unresolved
  outcomes whose evaluation time is still in the future.
- **Decision:** report future and settlement-grace outcomes as normal pending
  work; block soak approval only on overdue or unrecovered expired outcomes,
  and fail closed when the necessary timestamp schema is unavailable.
- **Why it worked:** regressions preserve approval eligibility with concurrent
  1/5/15-minute work and block independently on overdue and expired evidence.
- **Reuse:** every streaming pipeline whose normal in-flight work overlaps an
  approval or health audit.

### 2026-07-29 — Compare SHADOW variants on one immutable market window

- **Context:** waiting longer on one negative strategy only increases confidence
  in the same result; testing several candidates creates selection bias unless
  their evidence and hypotheses are aligned.
- **Decision:** record bounded one-factor candidates on the same snapshot and
  candles, preserve the current plan as each baseline, and require both the
  normal horizon/regime gate and configuration-level Holm correction.
- **Why it worked:** tests prove five distinct plans share one timestamp and
  baseline, TTL/veto outcomes are explicit, p-values are candidate-specific,
  and even statistically eligible evidence cannot authorize APPLY.
- **Reuse:** every parallel strategy experiment where multiple configurations
  compete for promotion from the same historical evidence.

### 2026-07-29 — Make migration evidence atomic with schema mutation

- **Context:** SQLite `executescript` commits independently, so a power loss
  could leave DDL applied without its `schema_migrations` evidence.
- **Decision:** let the runner own `BEGIN IMMEDIATE`; parse complete SQLite
  statements without transaction control; write the version record in the same
  transaction; reject duplicate versions before touching the database.
- **Why it worked:** injected SQL, version-record and bootstrap failures roll
  back every schema change and marker, while trigger-containing migrations and
  guarded legacy partial resumes pass.
- **Reuse:** every schema/bootstrap operation whose completion marker controls
  whether a service can safely start.

### 2026-07-29 — Make service shutdown and restart pressure explicit

- **Context:** a supervisor-only TERM combined with `KillMode=mixed` bypassed
  worker graceful handlers, while runtime-based failure reset missed slower
  crash loops.
- **Decision:** route supervisor TERM through the existing `STOPPING` cleanup,
  signal the complete control group, and base child backoff and alerting on a
  bounded rolling failure window.
- **Why it worked:** regressions prove first TERM enters graceful shutdown,
  repeated slow crashes back off and alert once, expired failures stop counting,
  and intentional cleanup clears its window.
- **Reuse:** every parent/child service whose safe shutdown and restart policy
  cross Python, subprocess and systemd boundaries.

### 2026-07-29 — Separate stored expense magnitude from display direction

- **Context:** exact commission accounting stores a positive expense magnitude,
  while an operator-facing financial report must show its negative effect.
- **Decision:** retain positive exact fee values in accounting and negate only
  at the report presentation boundary.
- **Why it worked:** the digest regression proves the fee is displayed with a
  minus while existing exact FIFO net PnL remains unchanged.
- **Reuse:** every report that presents non-negative stored costs, fees or
  slippage as signed account impact.

### 2026-07-29 — Require explicit restart authority in the watchdog

- **Context:** service inactivity alone cannot distinguish a crash from an
  operator's persistent stop, and recovery notifications must remain bounded
  and secret-safe through long network outages.
- **Decision:** restart only an enabled unit, treat disabled or masked inactive
  units as intentionally stopped, pass Telegram data through descriptors, cap
  and expire the durable outbox, and diagnose a missing route without guessing
  a gateway.
- **Why it worked:** regressions prove the watchdog performs no restart or
  alert for a disabled bot, exposes no Telegram data in argv, bounds queued
  messages and never probes a fabricated gateway.
- **Reuse:** every autonomous recovery loop that can mutate service state or
  retain outbound operational notifications.

### 2026-07-29 — Model replay latency and public liquidity symmetrically

- **Context:** exact-price maker matching missed better resting orders, while
  immediate cancellation let re-anchor avoid fills that remain possible in
  flight.
- **Decision:** let an aggressive public print reach equal-or-better local
  maker prices, conserve its quantity, apply venue latency to submit and cancel,
  and represent public FIFO depth once per same-price local queue.
- **Why it worked:** adversarial regressions prove price-through fills at the
  local limit, non-crossing orders remain open, pre-ACK cancels remain fillable,
  shared depth is not doubled and throttling performs no mutation.
- **Reuse:** every L2 simulation used to compare placement, cancellation or
  re-anchor behavior with real execution.

### 2026-07-29 — Restart only a coherently restored runtime

- **Context:** a failed in-place dependency installation can leave the checkout
  and virtual environment at different release boundaries.
- **Decision:** automatically restart the bot only after restoring the exact
  previous commit and its hashed dependency lock, and only before any external
  deployment asset was mutated. Otherwise keep execution and watchdog stopped
  while starting the dashboard for diagnosis.
- **Why it worked:** recovery regressions prove rollback precedes service
  restart and any unproven or externally partial state selects the stopped-bot
  branch.
- **Reuse:** every deployment that updates code, dependencies and system assets
  through separate non-transactional operations.

### 2026-07-29 — Preserve primary failure across mandatory cleanup

- **Context:** a cleanup failure can occur while a more important exchange or
  protection failure is already propagating from a bounded canary.
- **Decision:** keep the original exception authoritative for HALT and report
  status, attach cleanup failures as a separate bounded evidence list, and
  raise cleanup itself only when no primary failure exists.
- **Why it worked:** regressions inject simultaneous OCO rejection and cleanup
  failure, then prove the report and raised error retain the OCO cause while
  exposing cleanup evidence without signed request data.
- **Reuse:** every `finally` cleanup that runs after a financial mutation.

### 2026-07-29 — Bootstrap deployment from verified target code

- **Context:** an immutable copy of the installed updater avoids mixed code but
  cannot apply deployment steps introduced by the target release.
- **Decision:** before backup or service stop, verify target ancestry and
  signature, extract its updater from Git and execute it as the immutable
  runner; never do this for unsigned break-glass.
- **Why it worked:** ordering tests prove signature verification precedes
  extraction and target execution precedes every service mutation.
- **Reuse:** self-updating deployment tools whose post-checkout behavior changes
  between releases.

### 2026-07-29 — Decouple observational soak from execution authority

- **Context:** HALT must stop order workers, but readiness still requires
  authenticated stream observation and event-triggered REST evidence.
- **Decision:** operate a separate read-only observer whose only exchange
  calls are GET reconciliations and whose sanitized counters survive restarts.
- **Why it worked:** source-boundary, identity-mismatch, service and deployment
  tests prove the observer cannot mutate orders and can run under HALT.
- **Reuse:** telemetry, canary and soak collectors that need production inputs
  but must never inherit trading authority.

### 2026-07-29 — Separate persistent safety state from process runtime

- **Context:** systemd removes runtime directories across stop or reboot while
  circuit HALT evidence must outlive both.
- **Decision:** store authoritative control evidence in `StateDirectory`, keep
  only disposable process files under `/run`, and represent LIVE startup as
  `RISK_PENDING` until authoritative reconciliation completes.
- **Why it worked:** path, migration-order and startup-state regressions prove
  that HALT remains visible without allowing a transient BUY-ready status.
- **Reuse:** every daemon whose safety decision must survive its own lifecycle.

### 2026-07-29 — Make scheduled reports idempotent and retryable

- **Context:** a single transient WAL or delivery failure at the scheduled
  minute postponed an otherwise valid daily report until the next day.
- **Decision:** retain an application-level read-only SQLite connection, permit
  WAL coordination in the service sandbox, and retry a failed idempotent report
  twice with one deduplicated figure-free warning.
- **Why it worked:** delivery state prevents duplicates while bounded retries
  recover from transient database and notification failures.
- **Reuse:** every scheduled report or notification with a durable calendar key.

### 2026-07-29 — Use one dashboard body type scale

- **Context:** operational cards mixed browser-default 16 px text with explicit
  10, 11 and 12 px values, making related evidence look inconsistently ranked.
- **Decision:** use a 13 px dashboard baseline for all operational body text,
  with larger sizes reserved for section headings and primary KPI values.
- **Why it worked:** paired cards remain readable at equal visual weight while
  responsive tests preserve the single-column mobile layout.
- **Reuse:** every dashboard card, table, diagnostic disclosure and control.

### 2026-07-29 — Mirror every authoritative halt into risk telemetry

- **Context:** recovery can create the authoritative circuit-halt marker before
  the risk manager has produced its normal state snapshot.
- **Decision:** every manual or recovery halt atomically writes its marker,
  then atomically mirrors it into matching halted risk telemetry while
  preserving known equity fields.
- **Why it worked:** dashboard and Pi verification receive one consistent
  fail-closed state even when startup stops before the first risk evaluation.
- **Reuse:** every safety control whose authoritative marker and operational
  telemetry are stored separately.

### 2026-07-29 — Optimize defensive predictions for monetary decision value

- **Context:** direction accuracy treats a harmless small miss like a missed
  crash and does not reveal whether a regime gate improved trading economics.
- **Decision:** compare every defensive gate with the unchanged always-trade
  counterfactual in quote currency, weight confusion by realized move size,
  train only before a chronological cutoff, and forbid predictors from
  expanding baseline risk.
- **Why it worked:** regressions prove exact avoided-loss value, large-DOWN
  capture, no future-labelled training rows and an ensemble that can only veto
  BUY or preserve/reduce CAP.
- **Reuse:** prediction challengers, regime filters and any experimental signal
  proposed for execution.

## Entry format

### YYYY-MM-DD — Short decision title

- **Context:** the constraint or recurring problem.
- **Decision:** the chosen invariant or workflow.
- **Why it worked:** the evidence that validated it.
- **Reuse:** when future work should apply the same decision.

## Decisions

### 2026-07-29 — Lead position monitoring with the required operator action

- **Context:** one dashboard card mixed market value, incomplete PnL,
  protection legs, gap state, journal provenance and legacy inventory, making
  the urgent unprotected managed quantity difficult to see.
- **Decision:** preserve detailed evidence in the read-only API, but render one
  concise summary ordered as action, managed exposure, protection gap, BUY
  block, account total, legacy boundary and cost-basis availability. Keep
  healthy zero-valued stream counters out of the primary view and expose only
  non-zero diagnostics behind an explicit disclosure.
- **Why it worked:** presentation regressions prove internal status codes and
  TP/STOP detail are absent from the primary card while exact quantities remain
  escaped, localized and visually prioritized.
- **Reuse:** operational views where one required safety action matters more
  than the full diagnostic payload.

### 2026-07-29 — Keep advisory and telemetry I/O outside the protection hot path

- **Context:** synchronous SHADOW provider calls could delay deterministic
  worker launch by the full provider timeout, while commission valuation and
  telemetry persistence ran before fill protection.
- **Decision:** consume only cached AI advice in SHADOW and refresh it once per
  symbol in the background; after a fill, perform authoritative reconciliation
  and protection before any non-critical persistence. APPLY remains
  synchronous and every exchange protection verification remains authoritative.
- **Why it worked:** regressions prove SHADOW refresh returns immediately,
  concurrent refreshes are deduplicated, protection precedes telemetry, and
  OCO/gap safety behavior is unchanged.
- **Reuse:** advisory providers, analytics, logging and metrics adjacent to any
  latency-sensitive risk or position-protection path.

### 2026-07-29 — Separate defensive danger from harmless direction differences

- **Context:** strict label unanimity treated `FLAT` versus `UP` as a safety
  conflict and disabled a grid in the range regime it is intended to evaluate.
- **Decision:** group `FLAT` and `UP` as safe votes, retain a confident
  `DOWN`/`PANIC` veto, and let a weak danger vote only halve the already
  approved baseline CAP.
- **Why it worked:** regressions prove safe disagreement preserves baseline
  permission, weak danger cannot expand risk, and confident danger still
  blocks BUY.
- **Reuse:** veto-only ensembles where predictors disagree on opportunity but
  not on the presence of material downside.

### 2026-07-29 — Enforce the verification interpreter at the entry point

- **Context:** repeatedly documenting the correct `.venv` command did not stop
  accidental host-Python harness runs from failing before verification.
- **Decision:** when a repository `.venv` exists, re-execute the harness through
  it before project imports; preserve an explicit CI matrix interpreter only
  when no local venv exists, and fail closed on a re-exec loop.
- **Why it worked:** the formerly failing host-`python3` command now reaches
  harness help, while unit tests prove re-exec arguments, CI fallback and loop
  prevention without exposing environment contents.
- **Reuse:** dependency-heavy operator entry points whose canonical runtime is
  a repository-local virtual environment.

### 2026-07-29 — Revalidate at the database mutation boundary

- **Context:** a CLI can prove a preview still matches live exchange state, but
  a reusable library mutation must not assume every future caller repeats that
  time-of-check/time-of-use gate.
- **Decision:** require the cost-basis apply function itself to invoke a live
  revalidation callback before its write transaction, and persist any
  statistics-cursor discontinuity as audit evidence while warning the caller.
- **Why it worked:** stale and missing revalidation fail before lot mutation;
  migration and cursor-gap regressions preserve the exact range, and the
  complete 727-test suite passes.
- **Reuse:** preview/apply tools that archive, supersede or otherwise replace
  durable financial state after consulting an external authority.

### 2026-07-29 — Keep blocked analytics observable but compact

- **Context:** fail-closed recovery must keep SHADOW evidence current, but
  printing every computed ladder level on each observation hid the actual
  protection reason and grew the Raspberry Pi journal rapidly.
- **Decision:** expose the exact bounded runtime state in dashboard APIs and
  rate-limit blocked-plan summaries while leaving evidence calculation and
  persistence unchanged.
- **Why it worked:** dashboard and supervision regressions distinguish
  `RECOVERY_BLOCKED`, stale and unavailable states, prove no order mutation,
  and the complete 724-test suite passes.
- **Reuse:** any read-only telemetry loop that continues while an execution
  gate is closed.

### 2026-07-29 — Bound RAG by both market distance and retained evidence

- **Context:** cosine-only retrieval treated proportional quiet and extreme
  feature vectors as identical, while unbounded document scans made advisory
  latency grow with database history.
- **Decision:** combine cosine direction with normalized Euclidean distance,
  retain evidence for a fixed horizon, score only a bounded newest candidate
  set, and preserve time decay plus the non-future cutoff.
- **Why it worked:** regressions distinguish equal-direction magnitudes, remove
  expired documents and retrieval links, cap the Python candidate set, and
  still reject future or insufficient evidence.
- **Reuse:** any nearest-neighbor market retrieval where feature intensity and
  predictable runtime are both part of the contract.

### 2026-07-29 — Publish only the canonical main branch

- **Context:** merged release branches and a draft pull request remained
  visible after their commits were already published on the linear `main`
  release line, making completed work look unfinished or duplicated.
- **Decision:** keep temporary `ladderdragon/*` branches local, publish only
  `main`, enable automatic deletion after merge, and block creation of every
  other remote branch with an active GitHub ruleset.
- **Why it worked:** ancestry checks proved both remaining remote branches had
  no unique commits, their obsolete draft was closed, and the GitHub branch
  inventory contained only `main` after deletion.
- **Reuse:** every repository change and release; use local branches for
  isolation without leaving a second public line of development.

### 2026-07-29 — Preserve fail-closed state while collecting SHADOW evidence

- **Context:** startup recovery can block execution before the normal risk
  loop, while strategy evaluation still needs fresh non-executing evidence.
- **Decision:** acquire the supervisor singleton and normalize planning inputs
  before recovery, then run only `execution_allowed=False` observations while
  retaining the existing `RECOVERY_BLOCKED` heartbeat state.
- **Why it worked:** recovery regressions prove observations continue without
  any BUY, cancel or worker boundary and cannot publish a false `RUNNING`.
- **Reuse:** any advisory or counterfactual collector that operates while an
  execution gate is closed.

### 2026-07-28 — Keep the worker event loop incapable of creating BUYs

- **Context:** one 788-line function mixed resource lifecycle, initial BUY
  planning and long-running fill/protection reconciliation.
- **Decision:** keep preflight and initial planning in `worker.lifecycle`; pass
  an explicit mutable `WorkerLoopContext` into `worker.event_loop`, whose
  dependencies intentionally exclude every BUY placement service.
- **Why it worked:** lifecycle, recovery and safety regressions prove live
  `RUN` mutation remains visible, all resources are released after a cleanup
  failure and the event-loop source contains no BUY submission boundary.
- **Reuse:** long-running execution loops that must observe and reduce risk but
  must not independently create new exposure.

### 2026-07-28 — Keep transient preflight failures inside the supervisor

- **Context:** a slow Binance time read or `-1021` is unsafe for trading but
  does not require process death; systemd restarts only reset local retry
  context and create noisy loops.
- **Decision:** block BUY, publish a fresh `PREFLIGHT_BACKOFF` heartbeat and
  retry read-only preflight with bounded exponential delay. Resynchronize the
  exchange clock once after a definitive timestamp rejection.
- **Why it worked:** regressions prove the process survives RTT failure,
  watchdogs accept the fresh fail-closed state and signed URLs remain absent
  from errors and alerts.
- **Reuse:** temporary read-only exchange failures where no mutation has an
  unknown outcome and safety requires waiting rather than exiting.

### 2026-07-28 — Move mutable orchestration through a live state namespace

- **Context:** physically moving the worker loop could snapshot `RUN`, the
  SQLite connection or WebSocket transport and break SIGTERM and restart
  behavior.
- **Decision:** pass an explicit `WorkerRuntimeState` backed by the owning
  runtime namespace; reads remain late-bound and mode writes update that same
  namespace.
- **Why it worked:** focused regressions prove signal-style mutation and
  connection rebinding are visible after state construction, while worker
  safety, recovery, accounting and deployment contracts still pass.
- **Reuse:** long-running orchestration extraction where signal handlers or
  recovery code rebind process state after startup.

### 2026-07-28 — Import owning packages instead of compatibility aliases

- **Context:** module-identity replacement and historical import wrappers kept
  tests and extensions coupled to paths that no longer owned implementation.
- **Decision:** preserve executable CLI and ASGI entry points only; production,
  tests and extensions import the technical package owner directly.
- **Why it worked:** worker safety, accounting, AI, order, protection, Testnet,
  Mainnet and deployment contracts pass without the removed alias modules.
- **Reuse:** every remaining extraction; update callers in the same change
  rather than adding a compatibility import solely for old tests.

### 2026-07-28 — Inject legacy runtime adapters during physical extraction

- **Context:** supervisor tests and compatibility callers patch established
  runtime globals, while risk and recovery logic must move into package
  services without silently binding stale copies of those adapters.
- **Decision:** extracted services accept an explicit read-only runtime mapping;
  the legacy wrapper passes its globals and the service resolves only named
  dependencies at entry.
- **Why it worked:** recovery, reconciliation, re-anchor and architecture
  regressions still observe patched exchange, journal and accounting adapters,
  while the supervisor runtime shrank by 490 lines.
- **Reuse:** transitional extraction of cohesive LIVE orchestration whose
  dependency interfaces cannot be changed atomically.

### 2026-07-28 — Keep production source commentary English-only

- **Context:** operator logs, Telegram messages and technical comments must be
  understandable across deployment, review and incident-response environments,
  while localized UI copy still needs native-language resources.
- **Decision:** keep comments, docstrings and non-localized source text in
  English; allow other languages only in explicit locale files. Document
  invariants and dangerous sequencing rather than obvious syntax.
- **Why it worked:** a repository-wide source scan finds no Cyrillic outside
  locales, and AST regressions require English docstrings on critical nodes.
- **Reuse:** every production, deployment, dashboard and operator-script
  change.

### 2026-07-28 — Decompose behind stable compatibility facades

- **Context:** operator commands, systemd units and tests depend on established
  `bin` paths, while keeping application logic there creates monoliths and
  reverse package dependencies.
- **Decision:** move implementations into technical packages, leave thin
  import/CLI facades at historical paths, forbid package imports from `bin`,
  and lower non-growth budgets whenever a monolith shrinks.
- **Why it worked:** configuration, plan-runner and migration commands retain
  their old interfaces; 221 focused regressions pass and the supervisor loses
  284 lines without a flag-day rewrite.
- **Reuse:** every remaining supervisor, worker, dashboard, journal or
  prediction seam that must move without breaking deployment compatibility.

### 2026-07-28 — Preserve protection when reads are uncertain

- **Context:** a timeout while verifying a live OCO/OTOCO proves neither that
  protection is invalid nor that it is absent; cancelling on that uncertainty
  converts a read failure into an avoidable unprotected interval.
- **Decision:** never mutate exchange protection after an uncertain read.
  Halt with the existing list untouched. Record a terminal partial leg
  idempotently and replace protection only for the exact confirmed residual.
- **Why it worked:** OCO and OTOCO timeout regressions prove no cancellation or
  replacement occurs, while terminal partial STOP recovery remains idempotent
  and the next OCO quantity equals the residual.
- **Reuse:** every recovery flow where an uncertain observation is followed by
  a cancel, replace, cleanup, or other safety-reducing mutation.

### 2026-07-28 — Decompose behind stable compatibility facades

- **Context:** systemd, operator commands and tests depend on historical module
  paths, while keeping business logic in those entry points created
  multi-thousand-line monoliths.
- **Decision:** move implementations into technical package runtimes, preserve
  historical imports and commands with facades of at most 20 lines, then
  extract pure policies and repositories behind explicit boundaries. Reduce a
  checked line budget after every extraction.
- **Why it worked:** package-boundary tests reject reverse imports from `bin`,
  CLI/ASGI facades remain callable, and the complete regression suite exercises
  the same public contracts after each move.
- **Reuse:** every large runtime migration where deployment paths cannot change
  atomically with internal ownership.

### 2026-07-28 — Retry reads, reconcile mutations

- **Context:** blind HTTP retries can duplicate a mutation whose exchange
  acknowledgement was lost, while only the caller has the durable intent needed
  to determine the real outcome.
- **Decision:** allow bounded retries only for read-only requests; propagate a
  mutating network loss or 5xx as `UNKNOWN` and reconcile by `clientOrderId`.
  Retry a mutation only after a definitive `-1021` rejection and successful
  server-time synchronization.
- **Why it worked:** regressions prove one mutation network call, authoritative
  duplicate-ID recovery, bounded GET attempts, and fail-closed clock/418 paths
  without secret-bearing diagnostics.
- **Reuse:** every external API where a non-idempotent operation has a durable
  intent or idempotency key owned above the transport layer.

### 2026-07-28 — Normalize hot journal evidence without deleting audit history

- **Context:** OCO leg lookup and lifecycle telemetry scanned every historical
  metadata JSON document, while automatic retention would remove evidence used
  for recovery, accounting, and LIVE approval.
- **Decision:** store verified legs and exact closures in indexed normalized
  tables, commit multi-row lifecycle transitions atomically, and retain CLOSED
  intents indefinitely instead of deleting them in the runtime.
- **Why it worked:** injected mid-transaction failures roll back every related
  state and metadata write; tests also prove lookup and telemetry remain exact
  when legacy metadata JSON is unreadable.
- **Reuse:** durable journals, ledgers, and approval evidence where hot queries
  must remain bounded without weakening the audit trail.

### 2026-07-28 — Persist reusable agent learning in two focused records

- **Context:** useful fixes and root-cause lessons were scattered across chats,
  changelog entries, and review notes, so later changes could repeat them.
- **Decision:** require every agent to read `DECISIONS.md` and `MISTAKES.md`
  before editing, then record validated reusable choices and agent-caused
  failures in their distinct structured formats.
- **Why it worked:** repository tests enforce both files, their required fields,
  README discoverability, and the instruction in `AGENTS.md`.
- **Reuse:** every repository task; add entries only when a durable lesson
  exists rather than logging routine work.

### 2026-07-28 — Publish every semantic version as a continuous release

- **Context:** intermediate version commits without matching public tags made it
  difficult to prove whether changes were lost between releases.
- **Decision:** require one signed commit, one annotated tag, one PASS manifest,
  and one GitHub Release for every direct semantic successor on linear `main`.
- **Why it worked:** releases 2.20.57 through 2.20.60 were published
  sequentially, and each local/GitHub continuity check passed.
- **Reuse:** every release, including documentation-only releases.

### 2026-07-28 — Isolate exact accounting by symbol

- **Context:** incomplete ETH history blocked an otherwise valid daily report.
- **Decision:** calculate each symbol independently, exclude only symbols whose
  exact FIFO provenance cannot be proved, and never invent an opening lot or
  zero cost basis.
- **Why it worked:** mixed valid/incomplete-symbol regressions preserve exact
  eligible totals and identify exclusions explicitly.
- **Reuse:** financial reports, approval evidence, imports, and dashboard
  aggregations.

### 2026-07-28 — Confirm protection and emergency exits authoritatively

- **Context:** an attempted OCO or MARKET request is not proof that a filled BUY
  is protected or closed.
- **Decision:** accept protection only after verifying both Binance OCO legs;
  accept an emergency flatten only after a complete `FILLED` quantity and a
  durable journal commit.
- **Why it worked:** crossed-price, partial-fill, unknown-outcome, and recovery
  regressions remain fail-closed.
- **Reuse:** every order path that changes position or protection state.

### 2026-07-28 — Keep execution HALT separate from SHADOW observation

- **Context:** stopping execution also stopped the counterfactual evidence
  needed to improve BUY distance and re-anchoring.
- **Decision:** HALT blocks all mutations, while a healthy authenticated risk
  snapshot may still produce non-executing SHADOW observations.
- **Why it worked:** tests prove no worker or order mutation starts while
  advisory evidence continues.
- **Reuse:** experiments that need unbiased observation during a safety block.

### 2026-07-26 — Verify every published dashboard asset by hash

- **Context:** a healthy backend can still leave the dashboard unusable when
  HTML, CSS, JavaScript, or vendor assets are missing from the web root.
- **Decision:** compare every published asset with the exact release checkout
  and block deployment on a missing or mismatched file.
- **Why it worked:** deployment and Pi verification tests now fail closed on a
  missing or changed asset.
- **Reuse:** every static asset, nginx, dashboard, or deployment change.

### 2026-08-01 — Isolate dashboard section failures

- **Context:** one unavailable database or exchange endpoint stopped all dashboard updates.
- **Decision:** update each section independently and pause polling after HTTP 429.
- **Why it worked:** healthy host, AI, and history sections remain current during one source failure.
- **Reuse:** every read-only operational page that combines independent data sources.

### 2026-08-01 — Isolate deterministic static analysis

- **Context:** Semgrep and application audit tools require incompatible dependency versions.
- **Decision:** pin Semgrep in a separate hashed environment and run only local project rules.
- **Why it worked:** fixtures prove each rule, production scans need no network, and runtime dependencies remain unchanged.
- **Reuse:** every development tool whose dependency graph conflicts with the application environment.

### 2026-08-01 — Gate only statistically eligible observations

- **Context:** cold-start samples appeared in an approval gate without valid prior training history.
- **Decision:** use one chronological eligibility cohort for walk-forward results and production approval.
- **Why it worked:** tests prove cold-start rows cannot change the approval input.
- **Reuse:** every evaluation that trains on past data and approves future operation.

### 2026-08-01 — Require robust AI readiness evidence

- **Context:** five closures and a normal approximation could approve weak AI evidence.
- **Decision:** require 60 real closures and use a deterministic bootstrap confidence interval.
- **Why it worked:** small samples fail closed, and repeated audits return identical intervals.
- **Reuse:** every production gate that evaluates realized advisory outcomes.

### 2026-08-01 — Prove Mainnet stream events without enabling execution

- **Context:** a connected stream without order events cannot prove event-triggered REST reconciliation.
- **Decision:** submit one bounded non-taking order under HALT, cancel it immediately, and require zero execution.
- **Why it worked:** tests prove intent-first recovery, cleanup, persistent event evidence, and unchanged execution gates.
- **Reuse:** controlled authenticated stream drills on an otherwise idle account.

### 2026-08-03 — Use one conservative default fee

- **Context:** protection and reporting used different fallback fees for the same account setting.
- **Decision:** all consumers use the standard 0.1% Spot fee until the operator confirms a lower rate.
- **Why it worked:** breakeven, execution floors, and dashboard estimates now share one exact constant.
- **Reuse:** every account-cost default that affects protection, execution, or reporting.

### 2026-08-03 — Stop runtime before irreversible accounting retirement

- **Context:** a live writer could invalidate a clean audit before an exact-only schema rebuild.
- **Decision:** require explicit stopped-runtime evidence immediately before the retirement library call.
- **Why it worked:** a regression proves that an active runtime prevents backup and schema mutation.
- **Reuse:** every one-way database operation that follows a separate readiness audit.

### 2026-08-03 — Expose one Decimal order-planning API

- **Context:** completed Decimal migration left a parallel unused float planner beside production code.
- **Decision:** remove every float planner, result type, callback type, import, and test.
- **Why it worked:** production callers already use equivalent Decimal functions exclusively.
- **Reuse:** every completed financial type migration after repository-wide caller verification.

### 2026-08-03 — Limit cumulative User Stream reconnect rate

- **Context:** calendar soak age did not distinguish a stable stream from repeated disconnections.
- **Decision:** readiness permits at most one cumulative reconnect per observed hour.
- **Why it worked:** controlled drills remain eligible, while chronic reconnect churn blocks approval.
- **Reuse:** every duration gate whose subject can fail and recover during observation.

### 2026-08-03 — Start User Stream readiness from an immutable epoch

- **Context:** lifetime reconnect churn permanently blocked a later stable observation period.
- **Decision:** preserve lifetime counters and measure readiness from an append-only epoch baseline.
- **Why it worked:** old failures remain visible, while new evidence gets an independent denominator.
- **Reuse:** every repeated soak whose historical counters must remain immutable.

### 2026-08-03 — Keep bot log review inside product ownership

- **Context:** a global failed-unit scan included unrelated host software in an application review.
- **Decision:** review owned units and sanitized product logs; report other host failures separately.
- **Why it worked:** deployment tests prove the updater contains no `atop` or `rtl_tcp` management.
- **Reuse:** every application health review on a shared host.
### 2026-08-04 — Probe changed-IP authentication once each minute

- **Context:** generic exponential backoff delayed recovery after an operator updated the Binance allowlist.
- **Decision:** cap signed read retries at 60 seconds only while two-source evidence shows a changed public IP.
- **Why it worked:** other credential failures keep the longer backoff, and signed success remains authoritative.
- **Reuse:** identity changes that require external acceptance but permit cheap read-only verification.

### 2026-08-05 — Request a User Stream reconnect without a service restart

- **Context:** soak approval requires reconnect evidence, but the Mainnet event drill does not reconnect the persistent observer.
- **Decision:** `SIGUSR1` schedules one socket-only reconnect in the persistent shadow service.
- **Why it worked:** the signal handler performs no network work, and REST stays authoritative during recovery.
- **Reuse:** controlled transport drills that must preserve process age and service restart evidence.

### 2026-08-06 — Measure only unexpected transport reconnects as failures

- **Context:** planned idle socket renewal made a healthy User Stream fail its stability gate.
- **Decision:** gate the transport-failure rate and report idle, controlled, and total reconnects separately.
- **Why it worked:** tests accept expected renewal and reject repeated transport exceptions at the same rate.
- **Reuse:** every reliability gate that combines planned lifecycle events with unexpected failures.

### 2026-08-06 — Preserve fresh fail-closed runtime state

- **Context:** temporary exchange timeouts published `RISK_PENDING`, and the watchdog restarted the responsive supervisor.
- **Decision:** accept a fresh `RISK_PENDING` heartbeat as alive and fail-closed.
- **Why it worked:** the watchdog test proves no restart or unhealthy alert occurs for this state.
- **Reuse:** every watchdog where liveness and external dependency readiness are separate conditions.

### 2026-08-08 — Bound derived analytics, not source evidence

- **Context:** an append-only SHADOW database exceeded the Raspberry Pi temporary-sort capacity.
- **Decision:** keep all evidence and analyze the latest 1,000 decisions for each candidate.
- **Why it worked:** indexed row order removes the temporary sort and preserves every source row.
- **Reuse:** every growing evidence store with disposable operational summaries.

### 2026-08-08 — Separate replacement and active-entry comparisons

- **Context:** RANGE-only candidates have valid `NO_TRADE` outcomes outside RANGE.
- **Decision:** promotion includes opportunity cost, while a diagnostic cohort measures only active entries.
- **Why it worked:** the promotion question stays complete, and entry quality remains visible without selection bias.
- **Reuse:** every gated strategy whose valid action set depends on market state.

### 2026-08-08 — Require exact-time historical valuation

- **Context:** Binance can return a later candle when the requested minute is unavailable.
- **Decision:** require the exact candle minute and show portfolio change as unavailable otherwise.
- **Why it worked:** the dashboard never substitutes a current or future price for historical evidence.
- **Reuse:** every historical valuation or commission conversion from time-indexed market data.

### 2026-08-08 — Bind success status to one atomic artifact

- **Context:** an archive name could exist without proof that its backup operation completed.
- **Decision:** publish verified ciphertext atomically, then bind success to its name, size, and SHA-256.
- **Why it worked:** tests reject missing status, stale success, small files, and mismatched checksum evidence.
- **Reuse:** every dashboard status that summarizes a generated recovery artifact.

### 2026-08-08 — Preserve exact evidence across compatibility columns

- **Context:** unresolved-fill strings entered REAL columns before their exact companion columns.
- **Decision:** retain both column names, use TEXT affinity, and require equal values.
- **Why it worked:** tests preserve exact digits, round-trip legacy doubles, reject invalid evidence, and keep legacy queries compatible.
- **Reuse:** every compatibility schema that retains an older monetary column name.

### 2026-08-08 — Represent unknown financial cost as provenance

- **Context:** retroactive fill linkage lacks the expected price needed to prove slippage.
- **Decision:** store a compatibility zero with `unavailable` provenance and exclude the financial result from approval evidence.
- **Why it worked:** tests preserve lifecycle closure while readiness, RAG, and dashboard PnL reject incomplete costs.
- **Reuse:** every financial metric where a missing cost is not evidence of zero cost.

### 2026-08-08 — Keep failed horizon settlement pending

- **Context:** a historical price lookup can fail after its prediction horizon matures.
- **Decision:** preserve `NULL`, emit a safe diagnostic, and retry the same horizon later.
- **Why it worked:** tests reject current-price substitution and accept only the later successful exact-time lookup.
- **Reuse:** every retriable label or outcome whose source has authoritative time identity.

### 2026-08-09 — Drain historical labels without starving current work

- **Context:** a recent-time filter permanently excluded failed AI settlements after one day.
- **Decision:** select bounded oldest and newest due decisions from the complete history.
- **Why it worked:** tests settle old rows, bound each cycle, and preserve current work.
- **Reuse:** every retry queue that combines historical recovery with current results.

### 2026-08-09 — Retire zero-fill SHADOW entry gaps early

- **Context:** all version-four 40–50 basis-point candidates had zero fills after 319 resolved outcomes each.
- **Decision:** start immutable version-five candidates at explicit 15, 20, and 25 basis-point gaps.
- **Why it worked:** explicit prices remain distinct when the baseline gap is deeper.
- **Reuse:** every SHADOW generation whose tested action never occurs in a material sample.

### 2026-08-10 — Match experiment horizons to candidate lifetimes

- **Context:** 30-minute and 60-minute entry lifetimes were evaluated only through 15 minutes.
- **Decision:** version-six experiments use isolated 30-minute and 60-minute outcome horizons.
- **Why it worked:** a regression proves that a minute-45 fill distinguishes the two lifetimes.
- **Reuse:** every experiment whose parameter can act only after the standard observation window.

### 2026-08-11 — Preserve readable widths inside half-width cards

- **Context:** nested two-column grids reduced operational values to narrow fragments on common desktop widths.
- **Decision:** each half-width operational card uses one metric column with bounded labels and flexible values.
- **Why it worked:** desktop values retain 292 pixels at 1,266 pixels, while mobile rows stack vertically.
- **Reuse:** every dense dashboard card that already shares its parent row with another card.

### 2026-08-12 — Separate candidate selection from confirmation

- **Context:** shared future samples selected one SHADOW candidate and also supported its promotion gate.
- **Decision:** freeze one explicit manifest before collecting a new, purged confirmation cohort.
- **Why it worked:** roles, fingerprints, fixed windows, and append-only transitions prevent evidence reuse.
- **Reuse:** every adaptive experiment that selects a hypothesis from observed outcomes.

### 2026-08-12 — Make confirmation evidence block-native

- **Context:** snapshot-level inference did not match the predeclared confirmation windows.
- **Decision:** use identical selection snapshots and fixed confirmation blocks for all statistical inference.
- **Why it worked:** unresolved gaps cannot reorder evidence, and reports cannot change lifecycle state.
- **Reuse:** every time-series experiment with dependent observations and an explicit operator gate.

### 2026-08-13 — Bound exchange minimum adjustments by order direction

- **Context:** refreshed filters can make a planned LIMIT order smaller than the exchange minimum.
- **Decision:** increase only BUY quantity, use ceiling step rounding, and enforce the caller's quote budget.
- **Why it worked:** tests submit the exact minimum and block CAP excess or SELL quantity growth.
- **Reuse:** every final exchange boundary that can increase a planned order quantity.

### 2026-08-13 — Reconcile active intents through one network boundary

- **Context:** placement retries query Binance before deciding whether another mutation is safe.
- **Decision:** every failed active-intent lookup records `UNKNOWN` before the network error leaves the function.
- **Why it worked:** MARKET, OCO, and OTOCO tests preserve uncertainty and prevent a second POST.
- **Reuse:** every idempotent exchange mutation that begins with a remote state lookup.

### 2026-08-13 — Halt when filled BUY status is unavailable

- **Context:** protection cannot prove whether a watched BUY requires an exit order without its exchange status.
- **Decision:** emit a redacted diagnostic, halt mutations, stop the batch, and retain the complete retry queue.
- **Why it worked:** the failure test records one halt and preserves all pending order identifiers.
- **Reuse:** every protection loop where one unavailable source invalidates later batch decisions.

### 2026-08-14 — Keep SHADOW generations symbol-scoped

- **Context:** SOLUSDT required a new selection while ETHUSDT lacked mature outcomes.
- **Decision:** map each prediction symbol to one immutable generation and preserve all earlier evidence.
- **Why it worked:** SOLUSDT advances without resetting ETHUSDT or widening execution scope.
- **Reuse:** every multi-symbol experiment with different evidence maturity.

### 2026-08-16 — Calibrate zero-fill gaps from completed selection windows

- **Context:** ETHUSDT version eleven produced no fills at 38, 42, or 44 basis points.
- **Decision:** select version-twelve gaps from completed 60-minute SELECTION excursions before a fixed cutoff.
- **Evidence:** 278 complete windows ended by 2026-08-15 18:31 UTC; partial starting minutes were excluded.
- **Why it worked:** 19, 22, and 27 basis points produced historical touch rates of 13.67%, 10.79%, and 5.04%.
- **Reuse:** every zero-fill generation where one predeclared parameter can be recalibrated without future confirmation evidence.

### 2026-08-16 — Label operational evidence by its cohort scope

- **Context:** cumulative transport and execution evidence appeared beside newly started SHADOW generations.
- **Decision:** label historical totals explicitly and show separate cutoff-bounded progress for each active generation.
- **Why it worked:** the dashboard no longer presents mature infrastructure evidence as current candidate maturity.
- **Reuse:** every operational view that combines lifetime, certification, session, and experimental evidence.

### 2026-08-17 — Stage symbol promotion behind independent gates

- **Context:** BTCUSDT and ETHUSDT need execution preparation without execution authority.
- **Decision:** keep candidates outside execution until confirmation, two symbol CAPs, and explicit approval all pass.
- **Why it worked:** startup rejects premature scope changes before preflight or worker creation.
- **Reuse:** every SHADOW symbol considered for later execution.

### 2026-08-17 — Stream independent evidence from complete history

- **Context:** a 1,000-row model window could not contain 120 independent six-hour outcomes.
- **Decision:** stream append-only history and retain a bounded, prefix-stable set of independent snapshots.
- **Why it worked:** tests reach 120 units without loading overlapping rows into memory.
- **Reuse:** every statistical gate whose independent sample spacing exceeds its model history window.

### 2026-08-17 — Recheck inventory capacity before every LIVE BUY

- **Context:** current exposure below a CAP did not prove that the next order fitted inside it.
- **Decision:** reserve batch capacity in supervision and recheck balances plus open BUY orders before POST.
- **Why it worked:** a 0.01 USDT remainder cannot authorize a minimum-notional BUY.
- **Reuse:** every absolute exposure limit that controls a later exchange mutation.

### 2026-08-18 — Stop a mutation batch after uncertain submission

- **Context:** a lost acknowledgement leaves the accepted order and inventory commitment unknown.
- **Decision:** raise one typed uncertainty and stop every later BUY in the current batch.
- **Why it worked:** LIMIT and OTOCO tests prove that no second mutation follows an unresolved submission.
- **Reuse:** every mutation batch where one unknown result invalidates later capacity decisions.

### 2026-08-18 — Count walk-forward training by independent timestamp

- **Context:** one decision produces multiple outcome horizons but represents one market snapshot.
- **Decision:** purge overlap first, then count each retained timestamp once for training and evaluation.
- **Why it worked:** changing the number of horizons no longer changes cold-start sample meaning.
- **Reuse:** every multi-horizon time-series experiment with one decision per timestamp.

### 2026-08-18 — Separate binding effects from full-cohort safety

- **Context:** no-op control rows diluted measured effects but still represented operational safety.
- **Decision:** measure control benefit on binding rows and enforce non-inferiority on all rows.
- **Why it worked:** no-op rows cannot prove an effect, while they remain visible to safety checks.
- **Reuse:** every conditional control that changes only some baseline decisions.

### 2026-08-19 — Trade only an immutable activated CHAMPION

- **Context:** confirmed evidence did not identify one exact policy consumed by the LIVE worker.
- **Decision:** activate one append-only CHAMPION per symbol while every newer CHALLENGER remains SHADOW-only.
- **Why it worked:** worker startup reconstructs fixed policy values, and every order intent retains the activation fingerprints.
- **Reuse:** every adaptive strategy that researches replacements while a bounded production policy remains stable.

### 2026-08-19 — Bind promotion to exchange-faithful execution evidence

- **Context:** candle-touch evidence did not represent missed maker fills or stop-limit gaps.
- **Decision:** keep this evidence diagnostic and block CHAMPION promotion until an execution-faithful model exists.
- **Why it worked:** manifests now identify OCO leg types, account fees, and the incomplete execution model.
- **Reuse:** every strategy promotion whose exchange order lifecycle differs from its signal model.

### 2026-08-19 — Activate only the reviewed execution policy

- **Context:** separate preview and activation commands could accept different exposure limits.
- **Decision:** preview fingerprints all limits, and activation requires that exact fingerprint from a clean published release.
- **Why it worked:** any cap, manifest, report, checkout, or release change blocks activation.
- **Reuse:** every two-step operator action that converts reviewed evidence into mutation authority.

### 2026-08-20 — Confirm one exchange-faithful episode policy

- **Context:** candle outcomes could not prove maker queue behavior or stop-limit execution.
- **Decision:** preregister one SOL candidate and collect sequential compact L2 execution episodes.
- **Why it worked:** live confirmation now includes missed fills, partial fills, exact fees, and stop gaps.
- **Reuse:** every promotion where the exchange lifecycle differs from a candle-touch model.

### 2026-08-22 — Collect active execution evidence once per release

- **Context:** replay validation needs one real passive fill without enabling strategy execution.
- **Decision:** use one separately approved 6 USDT LIMIT_MAKER attempt under persistent HALT with mandatory cleanup.
- **Why it worked:** the durable marker blocks repeats, and the drill restores only its acquired SOL quantity.
- **Reuse:** every paid Mainnet validation that must not become an adaptive sampling loop.

### 2026-08-22 — Bind each mutation to one contiguous replay session

- **Context:** hourly archives did not cover complete order lifecycles.
- **Decision:** start public depth before POST and stop it after terminal cleanup.
- **Why it worked:** each replayed order now fits inside one verified source interval.
- **Reuse:** every external mutation used as empirical market-model evidence.

### 2026-08-22 — Aggregate replay sessions without joining gaps

- **Context:** validation needs multiple paid outcomes collected in separate sessions.
- **Decision:** preserve each archive and calibration, then assign each order to exactly one session.
- **Why it worked:** the report aggregates metrics without inventing market continuity.
- **Reuse:** every empirical gate built from separate bounded observation windows.

### 2026-08-22 — Evaluate the exact frozen episode contract

- **Context:** the episode evaluator used local thresholds instead of immutable manifest criteria.
- **Decision:** pass the frozen criteria into every look and reject unsupported contracts.
- **Why it worked:** one fingerprint now identifies both the candidate and its executed statistical test.
- **Reuse:** every promotion evaluator that consumes preregistered evidence.

### 2026-08-22 — Bound repeated Mainnet validation with one expiring batch

- **Context:** one attempt per release slowed evidence collection, while unrestricted retries could become adaptive sampling.
- **Decision:** reserve each attempt against fixed count, turnover, release, and expiry limits before mutation.
- **Why it worked:** crashes consume capacity, and every drill keeps its existing HALT and confirmation gates.
- **Reuse:** every paid production validation that needs several preregistered attempts.

### 2026-08-22 — Bind promotion to complete execution semantics

- **Context:** ordinary exits, protective exits, and execution regimes used different evidence boundaries.
- **Decision:** fingerprint one contract and attach it to every episode, manifest, replay gate, and CHAMPION policy.
- **Why it worked:** mixed semantics fail closed, while PANIC losses remain inside net expectancy.
- **Reuse:** every promotion where safety exits and normal exits share one production strategy.

### 2026-08-24 — Confirm only the executable entry policy

- **Context:** RECOVERY outcomes improved evidence although production blocks RECOVERY entries.
- **Decision:** start version 20 episodes only in executable regimes and bind all simulator inputs to the fingerprint.
- **Why it worked:** confirmation now measures the exact policy that a CHAMPION can execute.
- **Reuse:** every experiment whose runtime policy excludes states from its signal classifier.

### 2026-08-24 — Use bounded probation after CHAMPION activation

- **Context:** full SHADOW confirmation did not limit the first LIVE execution period.
- **Decision:** limit entries, turnover, duration, and equity loss during durable CHAMPION probation.
- **Why it worked:** the worker requires a fresh probation gate, and a loss breach creates persistent HALT.
- **Reuse:** every evidence-backed policy that enters production for the first time.

### 2026-08-24 — Separate engine proof from candidate expectancy

- **Context:** real drills validate order mechanics, while SHADOW episodes validate strategy geometry.
- **Decision:** reuse source-owned engine proof only across identical engine and fee domains.
- **Why it worked:** gap and target changes cannot inherit expectancy, but they do not require duplicate paid drills.
- **Reuse:** every strategy family that shares one unchanged exchange execution adapter.

### 2026-08-24 — Constrain the first CHAMPION to observed scale

- **Context:** one small validation episode did not support a larger concurrent inventory policy.
- **Decision:** require 6 USDT order and inventory limits, one position, and one closed probation lifecycle.
- **Why it worked:** activation and runtime now reject every unobserved exposure increase.
- **Reuse:** every first production activation with limited live-scale evidence.

### 2026-08-24 — Preregister a reachable execution-regime cohort

- **Context:** a multi-regime confirmation design could exceed its frozen episode budget.
- **Decision:** version 21 confirms RANGE only and freezes an e-process reachability proof.
- **Why it worked:** futility, readiness, and CHAMPION scope now evaluate one identical regime set.
- **Reuse:** every sequential experiment with rare states and a fixed observation ceiling.

### 2026-08-25 — Bind replay acceptance to one complete validation batch

- **Context:** mutable thresholds and selected sessions could create an optimistic replay PASS.
- **Decision:** fingerprint one acceptance policy and require the complete batch cohort during import.
- **Why it worked:** the importer recomputes PASS and rejects omissions, uncertainty, or policy changes.
- **Reuse:** every empirical proof assembled from multiple paid or safety-sensitive trials.

### 2026-08-25 — Distinguish readiness bounds from launch forecasts

- **Context:** a best-case statistical date appeared to predict production readiness.
- **Decision:** publish separate earliest, empirical, deadline, replay, and expected launch timestamps.
- **Why it worked:** unavailable execution proof now leaves launch timing explicitly unknown.
- **Reuse:** every release gate that combines independent evidence streams.

### 2026-08-26 — Separate entry diagnosis from frozen confirmation

- **Context:** adverse fills required longer paths without changing version 22 after review.
- **Decision:** collect append-only SHADOW paths through 360 minutes and select future vetoes with a fixed cutoff.
- **Why it worked:** current promotion stays immutable, while future selection measures entry quality without look-ahead.
- **Reuse:** every diagnostic that can inform a later generation but cannot change the current candidate.

### 2026-08-26 — Preserve promotion cadence before broad SHADOW coverage

- **Context:** sequential ETH and BTC reads delayed fixed SOL evidence beyond its event-gap contract.
- **Decision:** collect promotion symbols first, then rotate one observation-only symbol per blocked cycle.
- **Why it worked:** SOL keeps bounded cadence while every shadow-only symbol continues to receive evidence.
- **Reuse:** every shared scheduler that mixes promotion evidence with slower advisory sources.

### 2026-08-26 — Bind delayed diagnostics to retained public archives

- **Context:** an archive finished before its 360-minute post-fill diagnostic became complete.
- **Decision:** rescan retained metadata and load only archives that cover newly complete paths.
- **Why it worked:** matching is cheap before validation, and imported features retain the source hash.
- **Reuse:** every evidence join whose two immutable inputs mature at different times.

### 2026-08-27 — Preserve capture independently of evidence processing

- **Context:** file rotation and synchronous calibration interrupted public market history.
- **Decision:** keep one connection across hash-linked segments and process completed files in a bounded child.
- **Why it worked:** sequence and carried-book tests verify continuity without delaying capture for calibration.
- **Reuse:** continuous evidence collectors with slower derived-data consumers.

### 2026-08-27 — Generate historical opportunities from causal policy state

- **Context:** replay of known fills could not represent new opportunities after cancellation.
- **Decision:** replay independent policy slots against chronological public events and explicit historical context.
- **Why it worked:** cancellation latency, partial fills, and cadence determine new entries without future fill knowledge.
- **Reuse:** historical selection for policies that change future availability.

### 2026-08-29 — Observe safety context outside the execution worker

- **Context:** persistent HALT removed the worker-owned PANIC state required by historical selection.
- **Decision:** use one fresh, fingerprinted, public supervisor observer for PANIC evidence.
- **Why it worked:** HALT no longer removes context, while stale or incompatible state still blocks selection.
- **Reuse:** every observer whose evidence must remain available while execution is disabled.

### 2026-08-29 — Separate volatility selection from replay confirmation

- **Context:** fixed volatility boundaries never observed a high regime in retained calibration reports.
- **Decision:** freeze empirical boundaries before a disjoint, post-cutoff confirmation cohort starts.
- **Why it worked:** old data selects the policy, while new source hashes prove all fixed buckets.
- **Reuse:** every empirical boundary that affects a later readiness gate.

### 2026-08-29 — Remove public evidence only after external verification

- **Context:** continuous L2 capture had a capacity limit but no safe scheduled rotation.
- **Decision:** encrypt unreferenced segments externally, verify the bundle, then remove exact local files.
- **Why it worked:** mount, backup, reference, hash, and encryption failures preserve every local source.
- **Reuse:** every large derived or public evidence stream on limited storage.

### 2026-08-30 — Mirror only the newly created backup

- **Context:** each backup rehashed and recopied every retained archive.
- **Decision:** verify and mirror the current archive once, then retain earlier verified copies.
- **Why it worked:** backup cost now follows current data size instead of retained history size.
- **Reuse:** every append-only backup set with separately verified immutable archives.

### 2026-08-30 — Keep host liveness separate from load policy

- **Context:** responsive backup I/O exceeded a hardware watchdog load threshold.
- **Decision:** retain the device timeout and remove only the known default load gate.
- **Why it worked:** real stalls still stop watchdog petting, while managed maintenance stays online.
- **Reuse:** hardware watchdogs on hosts with expected I/O-intensive maintenance.

### 2026-08-30 — Keep L2 selection and confirmation physically disjoint

- **Context:** version 23 changes order availability through a delayed entry cancellation.
- **Decision:** select on reviewed L2 blocks and confirm only with new diff-depth source hashes.
- **Why it worked:** the importer verifies cutoff, model, policy, and source identity before one atomic evidence write.
- **Reuse:** every policy whose decision changes later market opportunities.

### 2026-08-30 — Separate deployment health from trading evidence

- **Context:** a monitoring audit can be blocked while a signed runtime remains technically valid.
- **Decision:** require its timer, but keep an immediate audit failure outside deployment rollback.
- **Why it worked:** installation remains atomic while trading approval stays fail-closed and visible.
- **Reuse:** monitoring evidence that is not required to execute the installed runtime safely.

### 2026-08-30 — Prove selection reachability at the producer boundary

- **Context:** the historical planner emitted too few independent time slots for its downstream importer.
- **Decision:** calculate maximum independent paths before publishing drafts and test the planner-to-importer contract.
- **Why it worked:** impossible evidence designs now stop before storage, operator review, or prolonged collection.
- **Reuse:** every preregistered evidence producer with a downstream count or spacing requirement.

### 2026-08-30 — Share immutable market parsing across policy candidates

- **Context:** 36 policies repeatedly verified and reconstructed the same L2 block.
- **Decision:** stream one verified block through a bounded batch of independent policy states.
- **Why it worked:** policy state remains separate while source verification and book reconstruction occur once.
- **Reuse:** deterministic parameter grids that consume the same immutable event sequence.

### 2026-08-30 — Reuse validated authority observations across advisory consumers

- **Context:** the supervisor and historical collector queried the same account commission endpoint independently.
- **Decision:** timestamp the validated runtime schedule and pass its narrow attestation to historical context.
- **Why it worked:** one authority read feeds both consumers without sharing credentials or remote payloads.
- **Reuse:** advisory evidence that needs a source already validated by the authoritative runtime.
