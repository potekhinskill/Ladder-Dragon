# Engineering decisions

Read this file before changing the repository. Record only decisions that were
validated by tests or production evidence and are likely to be reused. Keep
entries concise; this is not a changelog or an activity log.

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
