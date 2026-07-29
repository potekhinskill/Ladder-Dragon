# Engineering mistakes and root causes

Read this file before changing the repository. Add an entry whenever an agent
decision causes a defect, unsafe state, failed release, misleading output, or
avoidable rework. Identify the root cause rather than recording only the
symptom. Keep entries concise and exclude secrets, balances, account data, and
private infrastructure details.

## Entry format

### YYYY-MM-DD — Short failure title

- **Impact:** what failed or became misleading.
- **Root cause:** the controllable reason the decision failed.
- **Correction:** what fixed the immediate problem.
- **Prevention:** the rule or test that must stop recurrence.

## Mistakes

### 2026-07-29 — Verified a GPG signature inside a restricted trust store

- **Impact:** the first release command stopped before the harness and produced
  no artifact; the signed commit and repository contents were unchanged.
- **Root cause:** `git log --show-signature` was run where the GPG trust database
  was outside the permitted filesystem boundary.
- **Correction:** amend the learning record into the same atomic commit and run
  signature verification with the narrow Git/GPG permission boundary before
  starting the harness.
- **Prevention:** commit creation and signature verification must use the same
  explicitly authorized GPG boundary; never place a sandboxed signature probe
  before release verification.

### 2026-07-29 — Put an environment assignment after the timing executable

- **Impact:** one verification command exited before pytest and had to be
  repeated; repository and runtime state were unchanged.
- **Root cause:** `PYTHONPATH=.` was placed where `/usr/bin/time` expected the
  executable name instead of being applied by `env` before the timed command.
- **Correction:** run `env PYTHONPATH=. /usr/bin/time ...` and keep its exit
  status authoritative.
- **Prevention:** environment assignments for wrapped commands must precede the
  wrapper through `env`; never infer success from a timing command that did not
  print pytest collection or results.

### 2026-07-29 — Modeled placement and cancellation with unequal causality

- **Impact:** replay missed maker fills at better local prices, let re-anchor
  cancel without transport exposure and could count a shared public queue more
  than once, biasing execution and expectancy evidence.
- **Root cause:** matching was tied to literal public print equality,
  cancellation mutated state synchronously, and queue ownership was not made an
  explicit tested invariant.
- **Correction:** use price-through maker matching at the local limit, delay
  accepted cancels by venue latency, normalize one shared FIFO owner and return
  rate-limit rejection without mutation.
- **Prevention:** every matching-engine change must test adverse in-flight
  cancellation, better-price makers, conserved event volume and two local
  orders sharing one public price level.

### 2026-07-29 — Let a Linux-only syscall obscure a rewrite regression

- **Impact:** the first focused deployment run failed on macOS metadata-command
  syntax and a Markdown line wrap before validating the intended path rewrite.
- **Root cause:** the unit executed GNU `--reference` options outside its
  Raspberry Pi platform and compared raw wrapped prose.
- **Correction:** stub only the platform metadata calls, retain the literal
  rewrite execution, and normalize documentation whitespace.
- **Prevention:** cross-platform tests of deployment helpers must isolate
  platform-only syscalls and assert prose semantically rather than by wrapping.

### 2026-07-29 — Restarted services without restoring their release

- **Impact:** a failed dependency or asset update could restart LIVE execution
  from a new checkout with old or partially installed runtime components.
- **Root cause:** recovery remembered service state but not the previous Git
  identity, dependency lock or whether external deployment assets had already
  changed.
- **Correction:** record the previous SHA, restore its checkout and hashed
  dependencies before restart, and leave execution stopped whenever coherent
  rollback cannot be proved.
- **Prevention:** deployment recovery tests must inject failures before and
  after every non-transactional boundary and prove no mixed runtime can start.

### 2026-07-29 — Let a regression inherit an operator CAP

- **Impact:** the blocked-SHADOW regression passed locally but failed on every
  clean Linux runner, blocking publication and Raspberry Pi deployment.
- **Root cause:** the test asserted inventory-skew diagnostics without setting
  `BOT_CAP_PER_ORDER`; a developer-shell value activated that branch locally.
- **Correction:** set the required CAP explicitly inside the test.
- **Prevention:** every test that asserts a configuration-dependent branch must
  set or delete that environment variable with `monkeypatch`; parent
  environment values are never valid fixtures.

### 2026-07-29 — Hid the identity of a failed CI test

- **Impact:** all three Linux CI jobs reported one failure, but the verification
  artifact exposed only aggregate counters, forcing an avoidable diagnostic
  release before the root cause could be corrected.
- **Root cause:** child output was correctly excluded for secret safety, but the
  allowlist contained totals only and omitted the non-sensitive pytest node ID.
- **Correction:** retain only validated `tests/...::test_...` identifiers in
  failed-check metrics while continuing to discard tracebacks and values.
- **Prevention:** fail-closed verification reports must expose the smallest
  safe diagnostic identity needed to reproduce a failure.

### 2026-07-29 — Let canary cleanup replace the initiating failure

- **Impact:** simultaneous OCO and cleanup failures reported only the cleanup
  symptom, so the persistent HALT and private evidence could hide the actual
  exchange-side trigger.
- **Root cause:** the lifecycle raised a new `RuntimeError` unconditionally
  from `finally` without detecting the exception already in flight.
- **Correction:** preserve the primary exception and store cleanup failures in
  a separate report field; cleanup raises independently only on an otherwise
  successful lifecycle.
- **Prevention:** every post-mutation cleanup test must inject both a primary
  failure and a cleanup failure and assert root-cause preservation.

### 2026-07-29 — Described journal reload as process restart

- **Impact:** canary evidence could be interpreted as proof of SIGKILL and
  new-process recovery although it only reopened the durable journal object.
- **Root cause:** field, mode and documentation names used `restart` for a
  narrower persistence check.
- **Correction:** rename the API result, Testnet mode and harness check to
  `journal_reload` and state explicitly that crash recovery is not exercised.
- **Prevention:** verification evidence names must describe the exact tested
  boundary and must not imply a stronger fault model.

### 2026-07-29 — Repeated a Git metadata mutation inside the sandbox

- **Impact:** the first staging command failed to create `.git/index.lock`;
  working files were unchanged.
- **Root cause:** after confirming `.git` was read-only, the next metadata
  mutation still relied on an approved command prefix instead of explicitly
  requesting the required filesystem permission.
- **Correction:** stage the exact reviewed file set with narrow escalation.
- **Prevention:** once a session proves `.git` read-only, every later branch,
  index, commit or tag mutation in that session must request escalation.

### 2026-07-29 — Guessed a learning-document test after discovery

- **Impact:** one verification command attempted a nonexistent test path and
  masked that subcommand with `|| true`; no repository or runtime state changed.
- **Root cause:** the command mixed correct discovery with an inferred filename
  instead of executing the path returned by discovery.
- **Correction:** run the discovered `tests/test_documentation_assets.py`
  directly and keep its exit status authoritative.
- **Prevention:** never append a guessed test to a discovery command and never
  suppress pytest failure while validating a candidate.

### 2026-07-29 — Renamed a Git branch without checking metadata permissions

- **Impact:** the first local branch rename failed before changing repository
  state and had to be repeated with the required permission boundary.
- **Root cause:** the command assumed workspace write access also covered
  `.git`, although this session exposes Git metadata as read-only by default.
- **Correction:** request the narrow Git branch operation outside the
  filesystem sandbox.
- **Prevention:** inspect the active permission profile before every Git
  metadata mutation and escalate the exact operation when `.git` is read-only.

### 2026-07-29 — Grew a budgeted test monolith during a logging fix

- **Impact:** the second focused verification failed only the test-file
  non-growth budget.
- **Root cause:** the regression used vertically expanded assertion data in a
  file already capped by the architecture policy.
- **Correction:** keep the existing behavior test and express its small prefix
  sets compactly without raising the budget.
- **Prevention:** check line budgets before editing known monoliths and move
  substantial new cases into focused component files.

### 2026-07-29 — Required optional SHADOW diagnostics in a regression

- **Impact:** the first focused verification had one false failure even though
  rate limiting and evidence persistence behaved correctly.
- **Root cause:** the test required expectancy and statistical messages that
  are intentionally absent when their optional data providers are unavailable.
- **Correction:** require every unconditional diagnostic once and constrain
  optional diagnostics to at most once.
- **Prevention:** logging tests must distinguish unconditional lifecycle
  evidence from output guarded by optional provider availability.

### 2026-07-29 — Combined unrelated large evidence reads into one command

- **Impact:** the first audit output was truncated, so the required project
  records and production evidence had to be read again in bounded sections.
- **Root cause:** one command concatenated three long learning files and both
  attachments without estimating the output size first.
- **Correction:** count lines first, read policy files in bounded ranges and
  summarize repetitive logs with targeted searches and tag counts.
- **Prevention:** never combine independent large evidence sources in one tool
  call; size them first and allocate separate bounded reads.

### 2026-07-29 — Repeated manual SHA interpolation in the release command

- **Impact:** the first 2.20.86 release harness was interrupted after starting
  with an expected SHA different from the signed commit; nothing was tagged or
  published.
- **Root cause:** the command printed `git rev-parse HEAD` but separately
  hard-coded `--expected-sha`, repeating a documented failure instead of
  binding one opaque value.
- **Correction:** amend and re-sign the learning record, then derive
  `release_sha` once and pass that same variable to verification and every
  later release operation.
- **Prevention:** release commands must never contain a manually typed
  40-character commit ID; they must read the candidate into one shell variable
  in the same process that consumes it.

### 2026-07-29 — Continued deployment with the previous release's script body

- **Impact:** the first 2.20.85 update advanced the checkout but did not install
  its newly introduced systemd service; a second invocation was required.
- **Root cause:** the updater intentionally copied its installed version to an
  immutable runner before fast-forward, so code safety also froze all
  post-checkout deployment behavior at the previous release.
- **Correction:** verify the target commit before any service mutation, extract
  its updater directly from the trusted Git object and execute that immutable
  target runner.
- **Prevention:** every deployment feature test must prove it is owned by the
  verified target runner on the first invocation, not merely present after the
  checkout changes.

### 2026-07-29 — Changed a runtime path without its isolated dashboard fixtures

- **Impact:** the first complete 2.20.85 test run failed three dashboard
  fixtures and the monolith no-growth budget before release.
- **Root cause:** the implementation changed the production stream directory
  but retained tests that derived it from the heartbeat path, and added a
  module constant to a file explicitly forbidden to grow.
- **Correction:** inject the new directory explicitly in isolated fixtures and
  resolve it at the existing read boundary without increasing the monolith.
- **Prevention:** path migrations must enumerate production, deployment,
  harness and fixture owners together; no-growth files require a line-count
  check in the focused test set.

### 2026-07-29 — Coupled a required soak observer to a halted worker

- **Impact:** the 24-hour authenticated stream gate could not begin while HALT
  correctly prevented execution workers, creating pressure to remove a safety
  block before its evidence gate had passed.
- **Root cause:** notification-only telemetry shared the lifecycle of the
  component permitted to mutate orders, although observation did not require
  execution authority.
- **Correction:** run a separate GET-only observer with persistent sanitized
  state and keep the worker event path unchanged.
- **Prevention:** every readiness gate must be collectible under the safest
  compatible execution state; observational services must not inherit mutation
  lifecycle requirements without necessity.

### 2026-07-29 — Stored authoritative HALT in a volatile runtime directory

- **Impact:** stopping the owning systemd service removed its runtime directory,
  so a post-exit HALT write failed and restart telemetry could temporarily lose
  the authoritative safety marker.
- **Root cause:** persistent control evidence was placed below `/run` and an
  operator mutation path stopped the service before verifying that the HALT
  destination still existed and was writable.
- **Correction:** move HALT, risk state and alerts to systemd `StateDirectory`,
  migrate legacy evidence before service stop, fail on conflicting copies and
  keep LIVE BUY blocked as `RISK_PENDING` until reconciliation.
- **Prevention:** authoritative safety evidence must never depend on
  `RuntimeDirectory`; stop/restart/reboot tests must prove persistence, and
  mutation preflight must verify its fail-closed destination before exchange
  submission.

### 2026-07-29 — Published RUNNING before the first risk snapshot

- **Impact:** the dashboard briefly showed `RUNNING` and `risk_halted=false`
  during a slow startup even though execution remained blocked by the
  preflight HALT.
- **Root cause:** runtime status was initialized unconditionally and the
  in-memory BUY gate started false before authoritative risk evaluation.
- **Correction:** initialize LIVE as `RISK_PENDING`, preserve known HALT state
  and publish BUY blocked until a successful snapshot exists.
- **Prevention:** tests must distinguish process liveness from trading
  readiness and assert fail-closed telemetry throughout the startup interval.

### 2026-07-29 — Sandboxed a WAL reader as a static-file reader

- **Impact:** the scheduled daily digest could not open the live SQLite
  database, and its fallback Telegram warning was silently unavailable.
- **Root cause:** the service made the entire WAL directory read-only and the
  alert loader reread a file below a non-traversable directory instead of using
  the explicit variables systemd had already loaded.
- **Correction:** permit WAL coordination while retaining SQLite `mode=ro`,
  accept only known Telegram environment keys, and add bounded idempotent
  retries with deduplicated blocked warnings.
- **Prevention:** deployment tests for read-only WAL consumers must model
  sidecar access, and systemd `EnvironmentFile` consumers must be tested with an
  unreadable source path.

### 2026-07-29 — Guessed a full commit SHA for verification

- **Impact:** the first release-harness run used an incorrect expected SHA and
  was interrupted after doing avoidable work.
- **Root cause:** the command expanded the displayed short commit ID by
  invention instead of reading the exact 40-character object ID from Git.
- **Correction:** obtain the candidate with `git rev-parse HEAD`, amend this
  learning record into the same commit and rerun verification only with that
  exact value.
- **Prevention:** treat commit IDs as opaque identifiers; copy the complete SHA
  from Git and never derive, pad or reconstruct it.

### 2026-07-29 — Shipped prediction research without scale and semantic edge tests

- **Impact:** expanding splits rescanned and copied history quadratically,
  harmless `FLAT`/`UP` disagreement blocked BUY, stale open interest appeared
  unchanged, and directional drift inflated a volatility feature.
- **Root cause:** the initial contour tested cutoff safety and risk
  non-expansion but omitted large-dataset complexity, safe-label equivalence,
  distinct timestamp provenance and a constant-return feature fixture.
- **Correction:** use binary cutoffs over one immutable training store, group
  safe votes, require distinct OI observations and calculate population
  standard deviation.
- **Prevention:** every new research feature needs an adversarial semantic
  fixture, and every historical iterator needs a storage-sharing complexity
  regression in addition to no-look-ahead tests.

### 2026-07-29 — Relied on documentation to select the harness interpreter

- **Impact:** the first 2.20.77 release-harness command again stopped before
  checks because host Python lacked a project dependency.
- **Root cause:** the earlier correction documented `.venv/bin/python` but left
  the executable boundary permissive, so the same human command error remained
  possible.
- **Correction:** make the harness re-execute through the repository `.venv`
  before project imports and retain the selected interpreter only when no
  local venv exists.
- **Prevention:** enforce critical environment invariants in entry points and
  tests; documentation is guidance, not a reliable runtime gate.

### 2026-07-29 — Repeated a documented host-Python harness mistake

- **Impact:** the first 2.20.75 release-harness invocation stopped before any
  checks because the system interpreter lacked `websocket-client`.
- **Root cause:** the command used `python3` even though the repository already
  documents `.venv/bin/python` and this file contained the same lesson.
- **Correction:** rerun the unchanged candidate through the project virtual
  environment; all release checks passed.
- **Prevention:** every project executable, pytest and harness command must
  start with `.venv/bin/python`; use another interpreter only for an explicit
  version-matrix check.

### 2026-07-29 — Put RAG configuration back into the supervisor monolith

- **Impact:** the first focused 2.20.74 run failed the architecture budget
  because the supervisor runtime grew 13 lines above its non-growth limit.
- **Root cause:** environment-to-store construction was added at the call site
  instead of the existing prediction-shadow ownership boundary.
- **Correction:** move the bounded knowledge-store factory into
  `supervision.prediction_shadow` and keep the runtime call to one line.
- **Prevention:** before adding orchestration configuration, identify the
  technical owner and check monolith line budgets in the first focused run.

### 2026-07-29 — Published a policy commit without advancing the release

- **Impact:** all three Python CI jobs passed their tests but the unified
  harness correctly returned `BLOCKED`, leaving `main` red after branch cleanup.
- **Root cause:** the policy-only change was treated as exempt from the linear
  release invariant even though the repository explicitly requires
  documentation-only releases to advance the semantic version.
- **Correction:** include the policy commit in 2.20.74, update every public
  version surface, and verify it through the release continuity harness.
- **Prevention:** before any direct push to `main`, run the local harness
  against the prospective commit and either publish the direct next version or
  do not push.

### 2026-07-29 — Tested blocked SHADOW only inside the main runtime loop

- **Impact:** a startup recovery block left advisory decisions and prediction
  evidence stale for roughly 40 hours even though execution remained safely
  halted.
- **Root cause:** the earlier regression inspected only the post-startup risk
  branch and did not exercise the separate pre-RUNNING recovery retry loop.
- **Correction:** collect non-executing SHADOW evidence from the startup
  recovery loop and preserve its fail-closed status while doing so.
- **Prevention:** every blocked-observation test must cover both startup
  recovery and steady-state risk gates, including status and mutation checks.

### 2026-07-28 — Guessed a documentation test path during release repair

- **Impact:** the first post-documentation verification command stopped before
  collecting tests because the requested file did not exist.
- **Root cause:** the command inferred a likely filename instead of applying
  the repository rule to discover paths first.
- **Correction:** locate the documentation contract with `rg --files` and
  content search, then run the discovered test plus the complete suite.
- **Prevention:** every targeted pytest command must contain only paths copied
  from current discovery output, including apparently obvious policy tests.

### 2026-07-28 — Repeated manual expansion of an abbreviated release SHA

- **Impact:** the first 2.20.68 release-harness command stopped at its identity
  guard and had to be rerun; no tag, push or deployment occurred.
- **Root cause:** despite existing lessons, the command again used a manually
  typed 40-character identifier instead of reading the selected branch HEAD.
- **Correction:** resolve `git rev-parse HEAD` after every branch switch and
  pass that exact output unchanged to verification, tagging and deployment.
- **Prevention:** release commands must derive immutable identifiers from Git
  after checkout; a human-entered or expanded SHA is never an accepted input.

### 2026-07-28 — Measured lifecycle boundaries before final cleanup wiring

- **Impact:** the first worker decomposition checks failed on an incomplete
  dependency allowlist, a stale line budget and a source assertion that also
  matched the legitimate `WorkerResources.state` attribute.
- **Root cause:** architecture constraints were updated before the final
  lifecycle helper existed and one run-worker invariant was applied to the
  entire module instead of the function it was designed to protect.
- **Correction:** allow the explicit resource dependency, use the exact final
  line budget and narrow the double-qualification assertion to
  `state.state`.
- **Prevention:** finalize helper wiring before measuring budgets and scope
  structural source assertions to the AST node whose invariant they express.

### 2026-07-28 — Computed one retry delay from two wall-clock samples

- **Impact:** a focused auth-backoff test intermittently waited 29 seconds in
  the final slice instead of the configured 30 seconds.
- **Root cause:** failure registration and delay subtraction sampled epoch time
  separately, allowing a second boundary to pass between them.
- **Correction:** capture one failure epoch and use it for both the persisted
  deadline and the immediate delay.
- **Prevention:** derive a retry deadline and its first wait from the same clock
  sample; use monotonic time only after entering the wait loop.

### 2026-07-28 — Added resilience tests back into known test monoliths

- **Impact:** the architecture budget test failed, and inserting the new
  supervisor tests split the tail assertions of an existing test.
- **Root cause:** the patch targeted a nearby assertion instead of an exact
  function boundary and ignored the repository rule that new component tests
  belong in focused files.
- **Correction:** restore the original auth-policy assertions and move the new
  exchange and preflight regressions into dedicated component test modules.
- **Prevention:** inspect full enclosing function boundaries before patching
  tests and run architecture budgets immediately after adding test cases.

### 2026-07-28 — Snapshotted mutable worker state before initialization

- **Impact:** the restart-idempotency test returned before creating inventory
  lots because the extracted stats service still saw its initial null
  connection.
- **Root cause:** runtime adapters were resolved before the initializer mutated
  the worker-owned `STATS_CON` and `TOOLS_STATS` slots.
- **Correction:** refresh both mutable slots immediately after initialization.
- **Prevention:** injected adapter snapshots must be reacquired after any call
  documented to mutate their owning runtime state.

### 2026-07-28 — Audited only the outer extracted function scope

- **Impact:** two holdings safety tests failed because a nested rounding helper
  could not resolve `price_round_mode`.
- **Root cause:** dependency discovery inspected the outer function symbol table
  but did not recursively include its nested function scopes.
- **Correction:** inject the missing rounding policy and rerun worker safety
  tests.
- **Prevention:** dependency audits for extracted functions must recurse through
  every child symbol table before the first behavior run.

### 2026-07-28 — Searched package imports but missed a bin-to-bin dependency

- **Impact:** the first complete no-facade suite stopped during Testnet soak
  monitor collection.
- **Root cause:** the migration search covered `ladder_dragon` and tests first,
  but did not audit one production command importing another command module.
- **Correction:** import Testnet client contracts from their owning
  verification package and rerun full collection and tests.
- **Prevention:** before deleting a facade, search the entire repository for
  both absolute and relative references to its module path.

### 2026-07-28 — Set the worker budget before the final import line

- **Impact:** the first complete 2.20.67 suite had one architecture failure.
- **Root cause:** the line budget was measured before adding the service import
  that completed the wrapper wiring.
- **Correction:** set the budget to the final measured 2835 lines and rerun the
  complete suite.
- **Prevention:** measure budgeted modules only after all wiring and formatting
  changes are complete.

### 2026-07-28 — Extracted annotated worker code without postponed annotations

- **Impact:** the first worker contract run failed during module import before
  any test or trading path executed.
- **Root cause:** the extracted service retained runtime-only annotation names
  but did not carry over `from __future__ import annotations` from its source
  module.
- **Correction:** postpone annotation evaluation in the service and rerun the
  full worker compatibility set.
- **Prevention:** every mechanical function extraction must preserve module
  future imports before its first compile and collection check.

### 2026-07-28 — Repeated synthetic SHA and guessed harness option

- **Impact:** the first post-amend release harness exited before verification,
  so the commit could not be published on that attempt.
- **Root cause:** the command embedded the visible abbreviated commit prefix
  with zero padding and guessed `--json-out` instead of reading the parser
  output and using its documented `--output` option.
- **Correction:** record the failure, amend again, capture the new exact SHA
  from `git rev-parse HEAD`, and pass it unchanged with `--output`.
- **Prevention:** build release commands only after `--help`; never type,
  expand, or reuse a commit identifier manually.

### 2026-07-28 — Rewrote injected dependency names inside string keys

- **Impact:** two targeted risk reconciliation tests bypassed their patched
  accounting adapter and opened an incomplete fixture database directly.
- **Root cause:** a bulk identifier rewrite also changed quoted runtime mapping
  keys, although compatibility keys must retain the original global names.
- **Correction:** restore exact runtime keys and inject the patched daily
  metrics loader explicitly; rerun supervisor recovery tests.
- **Prevention:** after mechanical extraction, compare every dependency key
  against the source module symbol table before running behavior tests.

### 2026-07-28 — Put literal Cyrillic inside the English-source test

- **Impact:** the complete suite failed because the new detector's own regex
  contained literal Cyrillic range characters.
- **Root cause:** a new source-language test was added without first locating
  the existing repository-wide English-source regression and matching its
  Unicode-escape representation.
- **Correction:** express the Cyrillic block as `\\u0400-\\u04ff`, preserving
  detection while keeping the test source itself English-only.
- **Prevention:** search existing policy tests before adding a parallel guard;
  source scanners must satisfy the same policy they enforce.

### 2026-07-28 — Added docstrings without updating raw line budgets

- **Impact:** the first targeted documentation regression failed because six
  coordinator files exceeded their exact non-growth budgets by the newly added
  docstring lines.
- **Root cause:** the source-language change treated comments as behavior-free
  but overlooked that the architecture gate intentionally counts every line.
- **Correction:** raise each affected budget only to its exact documented line
  count, with no spare capacity, and rerun the architecture suite.
- **Prevention:** whenever comments or docstrings touch a budgeted monolith,
  update the exact budget in the same patch or extract enough code to keep the
  raw count below the existing limit.

### 2026-07-28 — Typed a synthetic SHA instead of resolving HEAD

- **Impact:** a candidate harness command received a wrong 40-character
  `--expected-sha`; the run exposed that the option was not enforced.
- **Root cause:** the command manually padded an abbreviated SHA rather than
  using the exact `git rev-parse HEAD` result already printed by the preceding
  command.
- **Correction:** enforce exact checkout matching inside evidence validation
  and rerun with the real full SHA.
- **Prevention:** derive immutable identifiers programmatically and make every
  verification option that claims an expected identity a mandatory equality
  gate.

### 2026-07-28 — Moved implementations without updating source-contract tests

- **Impact:** the first architecture regression run failed because a deployment
  test still searched the thin compatibility facade for configuration defaults,
  and new production modules lacked the required purpose header.
- **Root cause:** the move preserved runtime imports but did not inventory tests
  that deliberately inspect source ownership and repository metadata.
- **Correction:** point the contract test at the packaged implementation and
  add complete production headers to every new module and facade.
- **Prevention:** every module move must search for both imports and raw path
  references, then run source-contract tests alongside runtime regressions.

### 2026-07-28 — Extended a journal contract without preserving test doubles

- **Impact:** two protection regressions initially halted with `AttributeError`
  because lightweight journal doubles did not implement the new partial-exit
  query.
- **Root cause:** the integration called the new method unconditionally even
  though the protection boundary intentionally supports minimal journal
  substitutes in isolated safety tests.
- **Correction:** feature-detect the optional query and treat its absence as
  zero historical partial exits; the production journal still supplies the
  authoritative implementation.
- **Prevention:** when extending a dependency protocol, inspect its test doubles
  and either update all of them or add an explicit backward-compatible default.

### 2026-07-28 — Invented the suffix of an expected commit SHA

- **Impact:** the first release-harness process was started with an incorrect
  40-character `--expected-sha` and had to be interrupted before artifact
  generation.
- **Root cause:** the seven-character SHA printed by `git commit` was expanded
  manually instead of copying the authoritative `git rev-parse HEAD` output.
- **Correction:** record the mistake, amend once more, then pass only the exact
  full SHA returned after the final commit.
- **Prevention:** never construct, autocomplete or reuse a pre-amend SHA;
  capture `git rev-parse HEAD` after the final commit and copy it verbatim into
  verification and deployment commands.

### 2026-07-28 — Split tests by stale line numbers

- **Impact:** the first component-test split produced three syntax/indentation
  collection errors because two cuts landed inside functions and one copied an
  incomplete multiline import.
- **Root cause:** line numbers from the pre-helper-extraction audit were reused
  after the files had already changed.
- **Correction:** exactly rejoined the affected fragments, discovered current
  top-level `def` boundaries, split again there, and verified all 211 original
  tests were collected and passed once.
- **Prevention:** mechanical source splits must use current AST/top-level
  boundaries and run `pytest --collect-only` before executing tests or deleting
  any source fragment.

### 2026-07-28 — Used the host Python for a project smoke check

- **Impact:** the first supervisor version smoke stopped on a missing
  dependency before it could exercise the moved CLI.
- **Root cause:** the command used system `python3` instead of the repository's
  `.venv/bin/python`.
- **Correction:** reran the command with the project virtual environment and
  verified the compatibility CLI successfully.
- **Prevention:** use `.venv/bin/python` for every executable smoke and pytest
  command unless a matrix test explicitly selects another interpreter.

### 2026-07-28 — Guessed prediction test filenames repeatedly

- **Impact:** two prediction verification commands exited before collecting
  tests; no source or runtime state was changed.
- **Root cause:** nonexistent archive/walk-forward filenames were appended
  after discovery output instead of selecting only paths returned by
  `rg --files tests`.
- **Correction:** ran the two discovered prediction/re-anchor test files and
  then the complete project suite.
- **Prevention:** construct every multi-file pytest command solely from the
  current `rg --files tests` output; do not add inferred names afterward.

### 2026-07-28 — Repeated a guessed-test-path mistake

- **Impact:** a related-test command stopped without executing because
  `tests/test_executor_orders.py` was guessed but does not exist.
- **Root cause:** the test list was composed before applying the repository's
  existing lesson to discover paths with `rg --files`.
- **Correction:** discovered the actual execution test files and reran the
  complete targeted set successfully.
- **Prevention:** run `rg --files tests` before every multi-file pytest command;
  do not rely on module-to-test filename inference.

### 2026-07-28 — Backfill parsed exchange payload keys instead of stored keys

- **Impact:** the first schema-v2 migration regression failed because historical
  `verified_legs` metadata uses normalized snake-case keys, while the migration
  accepted only Binance camel-case payload keys.
- **Root cause:** the new backfill reused an input sanitizer without checking
  the actual persisted representation produced by that sanitizer.
- **Correction:** accept both the exchange input shape and the normalized
  historical shape, then persist one canonical representation.
- **Prevention:** migration tests must start from the previous on-disk
  representation, not only from current API-shaped fixtures.

### 2026-07-28 — Treated the MARKET journal sentinel as a numeric price

- **Impact:** two MARKET-order safety regressions failed before submission
  because journal deduplication tried to parse the `MARKET` marker as Decimal.
- **Root cause:** numeric canonicalization was applied to every `price` field
  without first checking the established contract for price-less market orders.
- **Correction:** preserve `MARKET` as a strict non-financial sentinel and use
  Decimal comparison for every actual price.
- **Prevention:** inspect all callers and include LIMIT plus MARKET contract
  tests whenever a shared order-field invariant changes.

### 2026-07-28 — Assumed a recovery test filename instead of discovering it

- **Impact:** the first targeted verification command stopped before running
  tests because `tests/test_executor_recovery.py` does not exist.
- **Root cause:** the command inferred a filename from the module name instead
  of selecting it from `rg --files tests`.
- **Correction:** use the existing `tests/test_worker_order_recovery.py` and
  rerun the complete targeted set.
- **Prevention:** discover test paths with `rg --files` before composing a
  multi-file pytest command.

### 2026-07-28 — Bumped the canonical version without updating README

- **Impact:** targeted version and deployment-documentation tests failed because
  README still advertised 2.20.61 while the candidate was 2.20.62.
- **Root cause:** the version bump patch updated `product_version.py` and
  `CHANGELOG.md` but treated README links as a separate concern and missed both
  public version surfaces.
- **Correction:** synchronize both README declarations with the canonical
  version before committing.
- **Prevention:** change all three version surfaces in one patch and run
  `tests/test_product_version.py` immediately after every bump.

### 2026-07-28 — Tried to verify the final version before publishing intermediates

- **Impact:** the 2.20.60 release harness returned `BLOCKED` even though its code
  tests passed.
- **Root cause:** the candidate was checked directly against published 2.20.56
  while signed 2.20.57 through 2.20.59 commits had not yet received tags.
- **Correction:** verify, tag, push, wait for CI, and publish each version in
  order.
- **Prevention:** never run or publish a later release as a substitute for its
  unpublished direct predecessors.

### 2026-07-28 — Used one brittle patch for several documentation files

- **Impact:** the documentation update failed to apply and had to be retried.
- **Root cause:** one patch coupled many files to an exact README line wrap, so
  one stale context invalidated the entire change.
- **Correction:** split the update into small file-scoped patches and inspect
  each diff.
- **Prevention:** use narrow patches for independent documents, especially
  large frequently edited Markdown files.

### 2026-07-26 — Published dashboard HTML without required style assets

- **Impact:** nginx returned 404 for dashboard CSS and JavaScript, leaving an
  unstyled, partially unusable page while the backend remained healthy.
- **Root cause:** post-deployment readiness checked the service and HTML but did
  not prove that every static asset from the same release was installed.
- **Correction:** restore the missing files and add exact asset publication and
  hash verification.
- **Prevention:** a missing or mismatched HTML, CSS, JavaScript, vendor, locale,
  or image asset must block deployment.

### 2026-07-25 — Allowed a test to inherit the production HALT path

- **Impact:** a fake-canary test on the Raspberry Pi wrote its expected halt
  state to the real control file and could block new BUYs.
- **Root cause:** the test process inherited the production `CB_HALT_FILE`
  environment instead of forcing an isolated temporary path.
- **Correction:** bind test halt state to a temporary path and keep fake clients
  isolated from live control files.
- **Prevention:** environment-dependent safety tests must explicitly override
  every mutable runtime path and assert that production paths are untouched.

### 2026-07-24 — Let SHADOW expectancy change worker behavior

- **Impact:** a mode documented as observation-only raised the effective SELL
  profit floor, contaminating SHADOW evidence with applied behavior.
- **Root cause:** `BOT_REQUIRED_EDGE_PCT` was exported to the worker without
  checking whether expectancy mode was `APPLY`.
- **Correction:** export execution-changing expectancy only in approved APPLY;
  retain fee evidence in SHADOW without modifying the plan.
- **Prevention:** every SHADOW boundary needs a regression proving identical
  execution output to the baseline.
### 2026-07-28 — Token rewrite skipped names inside Python 3.10 f-strings

- **Impact:** the mechanically extracted worker loop initially retained four
  unqualified runtime dependencies that would raise `NameError` on operator
  log paths.
- **Root cause:** Python 3.10 tokenization exposes an f-string as one string
  token, so the name-rewrite pass could not see expressions inside it.
- **Correction:** identify free globals with `symtable`, qualify the remaining
  f-string expressions explicitly and repeat static validation.
- **Prevention:** every token-based extraction must finish with a recursive
  free-global audit; never assume token replacement can inspect f-string
  expressions on every supported Python version.

### 2026-07-28 — Token rewrite qualified an attribute name twice

- **Impact:** four clock reads in the extracted worker loop initially became
  `state.time.state.time()` and would fail before or during execution.
- **Root cause:** the mechanical rewrite qualified every matching name token
  without excluding tokens already used as an attribute after a dot.
- **Correction:** restore `state.time.time()` and compare the normalized AST of
  the moved function against its pre-extraction source.
- **Prevention:** token rewrites must ignore attribute-name tokens and must pass
  an AST-equivalence check, not only compilation and free-global analysis.

### 2026-07-28 — Kept a source assertion tied to the pre-extraction name

- **Impact:** the first targeted worker test run had one failure even though
  the exchange-clock dependency remained unchanged.
- **Root cause:** the deployment test was moved to the new bootstrap file but
  still expected `TM._timestamp_ms` instead of its explicit runtime-state form
  `state.TM._timestamp_ms`.
- **Correction:** assert the new owner-qualified dependency and rerun the
  complete worker regression set.
- **Prevention:** when moving orchestration behind an explicit state object,
  update both the source path and owner-qualified contract in structural tests.
