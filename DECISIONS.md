# Engineering decisions

Read this file before changing the repository. Record only decisions that were
validated by tests or production evidence and are likely to be reused. Keep
entries concise; this is not a changelog or an activity log.

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
