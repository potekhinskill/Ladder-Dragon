# Engineering mistakes and root causes

### 2026-09-01 — Anchored paths only to L2 session start

- **Impact:** one daily context gap reduced throughput and made the confirmation deadline operationally unreachable.
- **Root cause:** path geometry ignored recurring context outages inside an otherwise continuous L2 session.
- **Correction:** intersect both continuity sources, realign after each gap, and align recorder sessions after backup.
- **Prevention:** test each fixed evidence schedule with its production maintenance gap.

### 2026-09-01 — Counted context availability as an executable trial

- **Impact:** one TREND_DOWN path made the twelve-path selection cohort mathematically unable to pass.
- **Root cause:** planner admission stopped after context export and ignored the frozen RANGE-only execution scope.
- **Correction:** scan the causal entry interval and admit only non-PANIC executable paths.
- **Prevention:** test every fixed cohort with unavailable, blocked, and non-executable source intervals.

### 2026-09-01 — Shared one evaluator cohort across two evidence origins

- **Impact:** concurrent live SHADOW results could alter fixed L2 confirmation path counts.
- **Root cause:** episode storage had no confirmation-origin filter at the report boundary.
- **Correction:** filter v23 confirmation by its immutable report-owned episode identity prefix.
- **Prevention:** bind each sequential cohort to one explicit source-origin policy.

### 2026-08-31 — Recalibrated sources without migrating their policy

- **Impact:** a complete schema-5 backlog could leave volatility readiness blocked permanently.
- **Root cause:** the background processor never called the existing deterministic migration after source readiness.
- **Correction:** prioritize frozen archives and invoke migration only at exact cohort completion.
- **Prevention:** every background schema upgrade must test its final consumer transition.

### 2026-08-31 — Counted replay files as statistical evaluations

- **Impact:** confirmation progress could hide a blocked importer or evaluator.
- **Root cause:** the planner counted directory entries instead of acceptance-boundary evidence.
- **Correction:** validate monotonic replay, hash, import, and evaluation counters.
- **Prevention:** progress counters must share the authoritative boundary named by their label.

### 2026-08-31 — Deferred an anytime-valid test until cohort completion

- **Impact:** v23 could not pass or reject early and had no capacity reserve for one lost path.
- **Root cause:** the planner treated a fixed cohort as one atomic publication instead of an ordered block sequence.
- **Correction:** freeze admission order, publish each three-path block, and add three provider-capacity reserve paths.
- **Prevention:** every sequential design must test its first operational look and its deadline attrition reserve.

### 2026-08-31 — Counted different volatility event populations

- **Impact:** calibration and runtime could assign different buckets to the same public market interval.
- **Root cause:** calibration counted carried books on trades, while runtime counted sequence-verified depth updates.
- **Correction:** share one depth-update measurement and fingerprint its event population across all consumers.
- **Prevention:** every empirical runtime metric must test identical source-event inclusion before policy selection.

### 2026-08-31 — Assumed nominal segment length guaranteed bucket separation

- **Impact:** release 2.20.277 could not freeze a replacement volatility policy on production reports.
- **Root cause:** tests covered exact windows and zero inflation separately, but not their production combination.
- **Correction:** test the combined distribution and use preregistered bucket-scoped safe boundaries.
- **Prevention:** every policy migration must replay the aggregate production shape before publication.

### 2026-08-31 — Used selection power as a capacity requirement

- **Impact:** v23 needed a perfect 12-of-12 selection result to fit its confirmation deadline.
- **Root cause:** uncertain fill-rate bounds controlled cohort size after provider capacity was already fixed.
- **Correction:** freeze 42 paths and treat the design effect as a planning target only.
- **Prevention:** deadline capacity and expected statistical power must remain separate contracts.

### 2026-08-31 — Shortened the volatility measurement with its publication cadence

- **Impact:** runtime buckets could differ from the buckets selected on 55-minute calibration archives.
- **Root cause:** the producer used one five-minute value for two distinct time contracts.
- **Correction:** measure 55 minutes, publish every five minutes, and verify both values everywhere.
- **Prevention:** every rolling metric must name and fingerprint its measurement and publication intervals.

### 2026-08-31 — Called batch coverage replay success

- **Impact:** a completed batch could still lack a filled required order type.
- **Root cause:** the batch status treated covered attempts as proof of execution-model readiness.
- **Correction:** use `COHORT_COMPLETE_NOT_REPLAY_READY` until immutable replay import verifies fills.
- **Prevention:** transport completion must never imply semantic model validation.

### 2026-08-31 — Ignored unused time inside provider sessions

- **Impact:** confirmation declared fifty-one paths reachable within a fourteen-day deadline.
- **Root cause:** the planner divided total wall time by path duration across forced reconnect boundaries.
- **Correction:** pack paths inside each twenty-four-hour provider session.
- **Prevention:** test deadline capacity at the provider session boundary.

### 2026-08-31 — Labeled a fixed reserve as a statistical bound

- **Impact:** confirmation capacity did not control the probability of receiving required filled outcomes.
- **Root cause:** the planner subtracted one success instead of estimating binomial uncertainty.
- **Correction:** invert simultaneous one-sided exact binomial tests before the confirmation cutoff.
- **Prevention:** every named statistical bound must state and test its confidence level.

### 2026-08-31 — Used completed segments for a faster runtime guard

- **Impact:** the BUY guard would block during the last twenty-five minutes of each segment.
- **Root cause:** the guard freshness limit was shorter than the immutable segment cadence.
- **Correction:** publish separate rolling telemetry every five minutes from the verified book.
- **Prevention:** compare every runtime freshness limit with its producer cadence.

### 2026-08-31 — Required every validation attempt to succeed

- **Impact:** one definite technical failure invalidated every successful result in the fixed batch.
- **Root cause:** the cohort had no preregistered attrition allowance.
- **Correction:** record twelve terminal outcomes and require at least ten covered attempts.
- **Prevention:** freeze technical attrition before any live validation result is visible.

### 2026-08-31 — Equated confirmation paths with filled episodes

- **Impact:** a 30-path cohort could require 29 fills and remain practically unable to pass.
- **Root cause:** planning used evidence thresholds directly without converting source attrition rates.
- **Correction:** derive path capacity from pre-cutoff lower bounds and a fixed attrition reserve.
- **Prevention:** every evidence planner must convert required outcomes through frozen source-rate bounds.

### 2026-08-31 — Required every volatility bucket as one global gate

- **Impact:** an unobserved high bucket could block confirmed low and normal execution indefinitely.
- **Root cause:** replay readiness confused model coverage with permission for every operating bucket.
- **Correction:** freeze confirmed buckets and block BUY in each unconfirmed bucket at runtime.
- **Prevention:** categorical promotion gates must bind permissions to independently confirmed categories.

### 2026-08-31 — Relied only on time-based local backup retention

- **Impact:** frequent releases filled local storage while every duplicate remained younger than fourteen days.
- **Root cause:** retention bounded archive age but not local bytes or duplicate count.
- **Correction:** enforce a free-space floor and remove only externally verified local copies.
- **Prevention:** mirrored backup retention must bound age, local capacity, and interrupted temporary files.

### 2026-08-31 — Removed capabilities required by the external ownership model

- **Impact:** retention still failed after exFAT-compatible directory creation and could not reduce disk pressure.
- **Root cause:** the unit removed all capabilities without testing access under the deployed mount-owner options.
- **Correction:** grant only DAC override and file-owner capabilities used by encrypted archive publication.
- **Prevention:** deployment tests must compare service capabilities with the ownership model of every writable path.

### 2026-08-31 — Applied Unix mode changes to an exFAT backup disk

- **Impact:** the first L2 retention run failed before encrypted archival and left disk pressure unchanged.
- **Root cause:** the runner used `install -m` although the established backup workflow documents exFAT semantics.
- **Correction:** create the external directory with `mkdir` and keep strict modes only on the local status directory.
- **Prevention:** deployment tests must prohibit chmod-dependent directory creation on the external backup path.

### 2026-08-31 — Counted source geometry before context readiness

- **Impact:** the planner reported six usable paths although no path could pass the context exporter.
- **Root cause:** block counting preceded the authoritative context validation boundary.
- **Correction:** export each candidate first and publish separate L2-ready and context-ready counts.
- **Prevention:** progress counters must use the same acceptance boundary as their downstream consumer.

### 2026-08-31 — Required an artifact to contain its own hash

- **Impact:** every valid historical selection artifact would fail v23 confirmation import.
- **Root cause:** the consumer expected a self-referential field excluded by the canonical storage contract.
- **Correction:** verify the stored JSON body against the SHA-256 identity owned by its database row.
- **Prevention:** immutable artifacts need one external identity authority and an end-to-end producer-consumer test.

### 2026-08-31 — Used two names for one backup configuration

- **Impact:** the depth retention unit skipped every run and allowed L2 storage to approach disk capacity.
- **Root cause:** the new unit referenced `backup.conf`, while installation and backup used `backup.env`.
- **Correction:** use the canonical file and trigger depth retention after successful backup publication.
- **Prevention:** deployment tests must compare each consumer with the installer-owned configuration path.

### 2026-08-30 — Ignored the provider connection lifetime in reachability

- **Impact:** the planner waited for a 24-hour-five-minute session that the provider always closes earlier.
- **Root cause:** preflight counted statistical slots but omitted the transport's maximum connection lifetime.
- **Correction:** use 12 provider-bounded paths and reject designs whose path duration exceeds the provider limit.
- **Prevention:** include external protocol limits in every evidence reachability test.

### 2026-08-30 — Treated `find -mtime` as an exact day threshold

- **Impact:** eligible local archives remained for almost one extra day and consumed constrained SD-card capacity.
- **Root cause:** the selector rounds file age down to complete days before applying `+N`.
- **Correction:** convert retention days to exact minute thresholds for every related artifact.
- **Prevention:** test retention boundary units and inspect the oldest retained artifact after deployment.

### 2026-08-30 — Paginated a continuously changing SQLite backup

- **Impact:** pre-update backup rewrote the large prediction database repeatedly and prevented release installation.
- **Root cause:** voluntary page boundaries let external WAL writes restart the online backup.
- **Correction:** copy one pinned snapshot and close each SQLite connection immediately.
- **Prevention:** prohibit paginated production backup and test the exact deployment script contract.

### 2026-08-30 — Checked threshold ordering instead of bucket reachability

- **Impact:** a valid-looking empirical policy could leave its required normal volatility bucket empty.
- **Root cause:** preflight checked distinct thresholds but did not count future bucket membership.
- **Correction:** count every selection bucket and split the positive tail for zero-inflated cohorts.
- **Prevention:** verify category reachability before freezing every empirical confirmation policy.

### 2026-08-30 — Scheduled retention by clock instead of backup completion

- **Impact:** retention could report BLOCKED before the encrypted backup published fresh status.
- **Root cause:** systemd ordering declared sequence only when both units were already scheduled.
- **Correction:** start retention from backup success and keep a later retry timer.
- **Prevention:** encode artifact dependencies as completion triggers, not assumed clock spacing.

### 2026-08-30 — Confused refreshed PANIC state with consumed PANIC state

- **Impact:** the first HALT context cycle could record a one-pass evidence gap.
- **Root cause:** the first correction tried to attest a refresh completed after the runtime decision boundary.
- **Correction:** prime the observer without a row, then attest the next cycle's consumed state.
- **Prevention:** test observation time and consumption time separately for every asynchronous evidence source.

### 2026-08-29 — Relied on exit cleanup for private backup staging

- **Impact:** interrupted updates retained private staging and reduced capacity for the next required backup.
- **Root cause:** staging cleanup ran only on shell exit, while local rotation ran after archive creation.
- **Correction:** remove old timestamp staging and expired completed copies before collection, then rotate again after publication.
- **Prevention:** test preflight ordering, strict directory grammar, minimum age, and newest-archive preservation.

### 2026-08-29 — Copied only the default maintenance path

- **Impact:** the first recovery helper could ignore a watchdog maintenance-path override.
- **Root cause:** the helper copied a default instead of receiving the existing resolved setting.
- **Correction:** pass the same maintenance file into both health and network recovery checks.
- **Prevention:** test inherited operator settings at each newly extracted host-control boundary.

### 2026-08-29 — Omitted a deployment source header

- **Impact:** the first complete regression rejected the new network recovery helper.
- **Root cause:** the helper had a license and docstring but omitted the required `Purpose:` maintenance header.
- **Correction:** add the English purpose header before candidate verification.
- **Prevention:** run deployment source-contract tests with focused tests for each new host helper.

Read this file before changing the repository. Add an entry whenever an agent
decision causes a defect, unsafe state, failed release, misleading output, or
avoidable rework. Identify the root cause rather than recording only the
symptom. Keep entries concise and exclude secrets, balances, account data, and
private infrastructure details.

### 2026-08-28 — Assumed a newer standard library in a packaging test

- **Impact:** the packaging regression test failed on the project Python 3.10 environment.
- **Root cause:** the test imported a parser available only in newer Python versions.
- **Correction:** validate the fixed package-data list with the existing standard-library literal parser.
- **Prevention:** check the supported interpreter before adding a dependency, including in tests.

### 2026-08-28 — Shipped a historical context consumer without its producer

- **Impact:** retained market archives could not supply complete historical policy replay inputs.
- **Root cause:** implementation tested injected context but omitted a production source-observation path.
- **Correction:** add a bounded source journal, a runtime observer, and read-only proof export.
- **Prevention:** test the complete producer-to-replay path and reject missing past data instead of substituting current values.

### 2026-08-27 — Coupled pre-fill selection to post-fill completeness

- **Impact:** valid historical L2 paths could not enter future veto selection after a later diagnostic gap.
- **Root cause:** the importer required a complete 360-minute diagnostic for a five-minute causal pre-fill feature.
- **Correction:** require an eligible terminal fill result and validate the independent source-hashed pre-fill archive.
- **Prevention:** define each evidence gate at the temporal boundary needed by its decision.

### 2026-08-27 — Read raw signed transport logs during an audit

- **Impact:** private diagnostic output included sensitive signed request material.
- **Root cause:** a broad text search inspected complete application messages instead of structured safe fields.
- **Correction:** use aggregated counters, fixed system units, and sanitized structured telemetry for production audits.
- **Prevention:** never inspect raw signed client messages during routine log diagnosis.

### 2026-08-26 — Treated one early not-found response as permanent uncertainty

- **Impact:** a rejected validation order closed the complete authorized batch without creating an exchange order.
- **Root cause:** uncertain POST recovery performed one immediate query and did not distinguish proven absence.
- **Correction:** use bounded stable-identity reconciliation and record a separate definite-failure terminal state.
- **Prevention:** test delayed visibility, proven absence, durable child evidence, and unresolved cleanup separately.

### 2026-08-26 — Ranked a veto on overlapping rows with instant cancellation

- **Impact:** a future entry filter could appear profitable without executable timing or independent evidence.
- **Root cause:** reporting computed independent rows but ranked candidates on all rows and removed vetoed fills immediately.
- **Correction:** select on independent L2 paths and replay signal, cancel arrival, fill uncertainty, and slot availability.
- **Prevention:** every counterfactual mutation must use the same timing and capacity constraints as execution.

### 2026-08-25 — Required multi-day coverage from an expiring batch

- **Impact:** execution replay could never satisfy its two-day readiness gate.
- **Root cause:** one cohort owned both bounded Mainnet attempts and broad public calibration coverage.
- **Correction:** use separate immutable order and read-only calibration cohorts.
- **Prevention:** prove that every time and count requirement can coexist before freezing a verification workflow.

### 2026-08-25 — Checked classifier semantics after worker creation

- **Impact:** a future CHAMPION could start a worker before a configuration mismatch failed closed.
- **Root cause:** the observational check remained after the deterministic worker launch.
- **Correction:** move complete classifier validation before the worker boundary and remove the unused option.
- **Prevention:** place every execution-semantic precondition before the first possible mutation path.

### 2026-08-24 — Named all cold-start delay as missing history

- **Impact:** active BTC and ETH training appeared stuck although independent live snapshots accumulated.
- **Root cause:** the readiness text named only the unavailable historical source and omitted live cold-start progress.
- **Correction:** expose both source counts and use one source-neutral cold-start reason.
- **Prevention:** progress diagnostics must name every evidence source that can satisfy the same gate.

### 2026-08-24 — Combined incompatible aggregate-trade selectors

- **Impact:** high-activity SHADOW symbols failed on the second aggregate-trade page and collected evidence slowly.
- **Root cause:** continuation retained `endTime` while adding `fromId`, which Binance rejects.
- **Correction:** use time bounds only on the first page and identifier-only continuation afterward.
- **Prevention:** pagination tests must assert every request parameter set, not only returned rows.

### 2026-08-23 — Compared an absent legacy fingerprint with an empty normalized fingerprint

- **Impact:** one interrupted version 18 episode blocked every version 19 SHADOW collection attempt after restart.
- **Root cause:** recovery normalized the absent field to an empty string, but result validation compared the raw missing value.
- **Correction:** normalize both start and result semantics fingerprints before identity validation.
- **Prevention:** test restart recovery with records created before each append-only schema extension.

### 2026-08-23 — Routed the execution regime to the wrong call

- **Impact:** all blocked SHADOW symbols stopped collecting, and SOL version 19 created no episodes.
- **Root cause:** the change added `execution_regime` to the AI context call instead of the evidence collector call.
- **Correction:** pass the confirmed regime only to the SHADOW evidence collector.
- **Prevention:** test call contracts through the blocked statistical SHADOW path before release.

### 2026-08-22 — Coupled immutable evidence to an execution-only plan error

- **Impact:** SOL version 17 stopped creating episodes during high volatility, although persistent HALT kept money safe.
- **Root cause:** the read-only collector reused an execution planner that raised before the immutable candidate collector ran.
- **Correction:** allow only SHADOW planning to retain the configured TP ceiling; keep execution rejection unchanged.
- **Prevention:** blocked-observation tests must inject an invalid adaptive plan and require evidence progress without mutation.

### 2026-08-22 — External rotation ran after the capacity-sensitive copy

- **Impact:** a full external disk blocked a safe Raspberry Pi update backup.
- **Root cause:** retention ran only after external archive mirroring completed.
- **Correction:** run bounded retention before mirroring and preserve the newest archive.
- **Prevention:** test the order of retention and capacity-sensitive writes.

### 2026-08-21 — Audited an unpinned runner bootstrap tool

- **Impact:** release 2.20.232 failed dependency CI before the Pi update.
- **Root cause:** the audit lock resolved `pip` transitively instead of declaring its safe version.
- **Correction:** pin the fixed `pip` release in the hash-locked audit environment.
- **Prevention:** contract tests must reject vulnerable bootstrap versions in every audited lock.

### 2026-08-21 — Treated a terminal gap as pending work

- **Impact:** active BTC and ETH selection reports stayed at zero independent samples despite later resolved outcomes.
- **Root cause:** the reader checked only `outcome_json` and did not read the immutable `terminal_reason`.
- **Correction:** skip known resolved terminal gaps without consuming an independence interval.
- **Prevention:** evidence-prefix tests must combine terminal gaps, later outcomes, pending rows, cutoffs, and unknown reasons.

### 2026-08-20 — Depended on a restricted user-level GitHub endpoint

- **Impact:** the hourly Star History workflow failed continuously and sent repeated GitHub notifications.
- **Root cause:** the workflow required the full Stargazer list and reduced each GraphQL failure to a generic `ValueError`.
- **Correction:** use aggregate metadata, bounded Pages state, daily reconciliation, and safe reason codes.
- **Prevention:** prefer aggregate APIs and test diagnostics for each external data-access boundary.

### 2026-08-19 — Trusted a caller-selected HALT file

- **Impact:** any existing file could satisfy the CHAMPION activation precondition while the authoritative HALT was absent.
- **Root cause:** the CLI accepted a path and checked file existence without using Risk Manager configuration or marker validation.
- **Correction:** remove the path option and hold the configured HALT lock through the activation database write.
- **Prevention:** a safety precondition must resolve its authority internally and validate its complete evidence contract.

### 2026-08-18 — Applied a new training boundary to superseded generations

- **Impact:** each production SHADOW symbol reported `ValueError` after release 2.20.224.
- **Root cause:** the report path selected one current statistical design for active and historical generations.
- **Correction:** resolve the design from each report generation before selecting training evidence.
- **Prevention:** test current and superseded generations together with overlapping historical timestamps.

### 2026-08-18 — Used a power formula for the wrong test

- **Impact:** the first draft produced a sample size that did not match the approval hypothesis.
- **Root cause:** the design used a mean-test approximation while approval used an exact sign test.
- **Correction:** calculate exact binomial power with the Holm-adjusted first-test threshold.
- **Prevention:** derive power from the same test, direction, correction, and effect used by the gate.

### 2026-08-18 — Reconstructed a release SHA

- **Impact:** the first release verification was blocked before publication.
- **Root cause:** the expected SHA was manually expanded from abbreviated commit output.
- **Correction:** obtain the immutable candidate only with `git rev-parse HEAD`.
- **Prevention:** never type, infer, or reconstruct a release SHA.

### 2026-08-18 — Allowed evidence semantics to differ from execution

- **Impact:** a confirmed maker candidate could theoretically authorize a worker with different gap or time-to-live settings.
- **Root cause:** promotion checked lifecycle evidence but lacked an executable-policy fingerprint.
- **Correction:** promotion now fails closed until worker startup can verify the frozen policy.
- **Prevention:** bind every promotion artifact to the exact configuration consumed by execution.

### 2026-08-18 — Used a chronological prefix for rare controls

- **Impact:** low-frequency binding rows after the reader limit could never reach the approval gate.
- **Root cause:** bounded memory stopped the scan instead of prioritizing decision-relevant rows.
- **Correction:** the reader scans the cohort and retains bounded binding and non-binding groups separately.
- **Prevention:** capacity tests must include useful evidence after more than one full buffer.

### 2026-08-18 — Replaced open dashboard panels during polling

- **Impact:** an opened experiment history panel closed at the next five-second refresh.
- **Root cause:** the renderer replaced the complete subtree without preserving native `details` state.
- **Correction:** identify each history panel by symbol and generation, then restore its `open` attribute.
- **Prevention:** test interactive state across every polling redraw that uses `innerHTML`.

### 2026-08-18 — Derived applicability only from resolved evidence

- **Impact:** a new observation-only cohort temporarily reported a stateful-model block instead of `NOT_APPLICABLE`.
- **Root cause:** applicability lived only in unresolved metadata and was unavailable to the current gate reader.
- **Correction:** pass configured execution scope directly to the gate and include it in cache identity.
- **Prevention:** verify new status semantics before and after the first outcome resolves.

### 2026-08-18 — Mixed training rows into configuration selection

- **Impact:** cold-start outcomes could change configuration p-values and Holm decisions after the approval gate excluded them.
- **Root cause:** the walk-forward module did not expose its evaluation cohort to the experiment selector.
- **Correction:** use one explicit post-training cohort for every selection statistic.
- **Prevention:** test that changed training outcomes cannot change a selection result.

### 2026-08-18 — Let a generic report overwrite specialized control evidence

- **Impact:** runtime status could temporarily replace control-specific policies with an unrelated generic gate.
- **Root cause:** two producers shared one cache without a single ownership contract.
- **Correction:** permit only the specialized control loader to populate the cache.
- **Prevention:** each approval cache must have one policy-specific producer.

### 2026-08-17 — Added comments beyond a coordinator budget

- **Impact:** the complete suite failed because two comment lines enlarged the legacy supervisor coordinator.
- **Root cause:** the edit did not check the known line budget before it changed a full module.
- **Correction:** keep the explanation in the focused control-gate module and restore the coordinator budget.
- **Prevention:** check architecture budgets before all edits, including comment-only changes.

### 2026-08-17 — Counted overlapping outcomes as independent evidence

- **Impact:** frequent snapshots overstated statistical sample size and could permit unreliable promotion.
- **Root cause:** grouping horizons by snapshot did not remove dependence between adjacent snapshot outcomes.
- **Correction:** purge starts through the inclusive maximum horizon before inference and confirmation blocking.
- **Prevention:** define and test the independent outcome interval before setting any sample threshold.

### 2026-08-17 — Placed an absolute CAP inside an optional control

- **Impact:** a SHADOW inventory-skew mode could leave the absolute symbol inventory limit outside Risk Manager enforcement.
- **Root cause:** safety and optimization shared one code path and one mode switch.
- **Correction:** move the absolute per-symbol CAP into unconditional Risk Manager evaluation.
- **Prevention:** an optimization mode must never own a non-optional loss or exposure boundary.

### 2026-08-17 — Reused one approval gate for unrelated controls

- **Impact:** evidence for one strategy adjustment could authorize three adjustments with different semantics.
- **Root cause:** the implementation treated a group of control modes as one candidate strategy.
- **Correction:** collect separate baselines, evidence kinds, gates, and approval variables.
- **Prevention:** each independently switchable execution control needs its own counterfactual identity.

### 2026-08-17 — Named a nonexistent focused test module

- **Impact:** the first focused command stopped before test collection.
- **Root cause:** the command inferred a module name instead of resolving the test path.
- **Correction:** locate the real tests before the next focused run.
- **Prevention:** use `rg --files tests` before naming an unfamiliar test module.

### 2026-08-16 — Missed a source contract for a dependent default

- **Impact:** the first complete suite failed after focused behavior tests passed.
- **Root cause:** the initial search found the contract module, but the patch updated only behavior tests.
- **Correction:** require the dynamic symbol path in the deployment source contract.
- **Prevention:** inspect each source-contract match before changing an operator default.

### 2026-08-16 — Inserted a test before an existing final assertion

- **Impact:** the first focused run failed after the new test consumed the wrong captured output.
- **Root cause:** the patch matched an intermediate assertion instead of the complete function boundary.
- **Correction:** restore the L3 assertion to its original test before rerunning the focused set.
- **Prevention:** inspect the complete enclosing test after inserting a new top-level function.

### 2026-08-16 — Let control placeholders change financial baselines

- **Impact:** a UTC-day control action could replace real equity baselines with zero.
- **Root cause:** financial loading and control-state loading shared one required equity argument.
- **Correction:** control actions load without equity and cannot advance the financial day.
- **Prevention:** placeholder financial values must never cross an authoritative state transition.

### 2026-08-16 — Fixed symbol evidence beside a variable symbol

- **Impact:** a non-SOL Pi profile could audit the stable SOL User Stream file.
- **Root cause:** the parser assigned independent defaults to a symbol and its evidence path.
- **Correction:** derive the default path after symbol normalization and validation.
- **Prevention:** dependent CLI defaults must resolve from one validated source value.

### 2026-08-16 — Let verification registries drift from behavior

- **Impact:** profile names and numeric boundaries could change outside their declared registries.
- **Root cause:** one registry was unused, and the numeric audit retained its original file list.
- **Correction:** gate profile resolution through its registry and add active risk and accounting modules.
- **Prevention:** each verification registry must have a test for every declared and critical member.

### 2026-08-16 — Let one report page expose a raw source failure

- **Impact:** a temporary network failure stopped the PnL report with a traceback.
- **Root cause:** pagination called the signed transport without a bounded retry and error boundary.
- **Correction:** retry complete pages and return a controlled nonzero report result.
- **Prevention:** each remote pagination loop must test temporary and persistent source failure.

### 2026-08-16 — Published a constant as proof

- **Impact:** scenario status claimed that execution scope was verified when it only described two input lists.
- **Root cause:** the function name and Boolean field promised more than the implementation checked.
- **Correction:** remove the proof claim and publish only derived symbol scopes.
- **Prevention:** a status field must identify its evidence or use descriptive wording.

### 2026-08-16 — Counted protection legs across the account

- **Impact:** complete OCO lists could hide a separate uncovered Testnet position.
- **Root cause:** the monitor compared one account-wide leg count with a single-position threshold.
- **Correction:** validate each OCO structure and compare its shared quantity with the account position.
- **Prevention:** protection checks must prove covered quantity for every monitored position.

### 2026-08-16 — Left the long soak loop without source recovery

- **Impact:** one source failure could discard many hours of Testnet validation progress.
- **Root cause:** the monitor wrote its report only after a normal loop exit.
- **Correction:** checkpoint failures, retry temporary errors, and block after a fixed consecutive limit.
- **Prevention:** long verification loops must persist progress before every recoverable retry.

### 2026-08-15 — Documented a service without its timer

- **Impact:** the first complete regression stopped at the systemd inventory contract.
- **Root cause:** the command reference added the service but omitted its separate timer unit.
- **Correction:** add both units and rerun the complete regression.
- **Prevention:** compare every new service and timer against the complete deployment unit inventory.

### 2026-08-15 — Built new SQLite fixtures from memory

- **Impact:** two focused runs stopped before validating retention and exact-next-candle behavior.
- **Root cause:** test slices and placeholder counts were not checked against their intended evidence shape.
- **Correction:** remove the anchor candle explicitly and match every declared fixture column.
- **Prevention:** inspect fixture identities and schema column counts before the first focused run.

### 2026-08-14 — Increased the deadline without removing sequential remote work

- **Impact:** `/api/trades/summary` still timed out after the client deadline increased to 20 seconds.
- **Root cause:** one request still performed several sequential Binance reads with separate ten-second limits.
- **Correction:** return local accounting immediately and refresh remote valuation through one bounded cache worker.
- **Prevention:** measure the complete dependency path before changing only its outer deadline.

### 2026-08-14 — Added cache logic to a full runtime module

- **Impact:** the first implementation exceeded the dashboard runtime architecture budget.
- **Root cause:** the component budget was checked after the first patch instead of before it.
- **Correction:** move the reusable cache into a focused service module.
- **Prevention:** check the architecture budget before selecting the destination for new logic.

### 2026-08-14 — Selected a nonexistent documentation test

- **Impact:** the first focused test command stopped before it evaluated the change.
- **Root cause:** the command guessed the test suffix instead of reading the collected function name.
- **Correction:** locate the exact function and rerun the focused suite.
- **Prevention:** search the test definition before using a node identifier.

### 2026-08-14 — Passed an option-like search pattern without a delimiter

- **Impact:** one documentation search stopped before it returned results.
- **Root cause:** the pattern started with `--profile`, and `rg` parsed it as an option.
- **Correction:** repeat the search with the explicit `--` argument delimiter.
- **Prevention:** use an argument delimiter when a search pattern can start with a hyphen.

### 2026-08-14 — Attempted staging without metadata permission

- **Impact:** the first staging command stopped before it changed the index.
- **Root cause:** the command ignored the read-only Git metadata boundary in the active permission profile.
- **Correction:** stage the exact reviewed file set with the required narrow permission.
- **Prevention:** inspect Git metadata permissions before the first index, branch, commit, or tag mutation.

### 2026-08-14 — Used a shorter client deadline than valid responses

- **Impact:** successful backend responses could appear unavailable, while the footer hid the affected section.
- **Root cause:** the deadline ignored measured production latency, and concurrent results discarded section identity.
- **Correction:** increase the bounded deadline and retain safe section names for failed requests.
- **Prevention:** compare each client deadline with measured latency and preserve request identity through concurrent aggregation.

### 2026-08-14 — Initialized a regime hold at the Unix epoch

- **Impact:** the first confirmed regime change bypassed its configured minimum hold after each process start.
- **Root cause:** the classifier initialized its transition timestamp to zero instead of the active clock.
- **Correction:** initialize the timestamp from the monotonic clock and retain zero as an explicit disabled duration only.
- **Prevention:** test the first transition at both sides of every time-based hold boundary.

### 2026-08-13 — Treated attempted flatten orders as accepted

- **Impact:** time-stop and hard-cap paths could report progress while no SELL order existed.
- **Root cause:** callers ignored optional placement results and reduced local tracking state unconditionally.
- **Correction:** preserve tracking after rejection and count only accepted submissions within the available remainder.
- **Prevention:** every mutation caller must test the returned acceptance evidence before it changes local progress.

### 2026-08-13 — Used EMA smoothing for ATR

- **Impact:** the worker PANIC volatility band reacted faster than the documented Average True Range semantics.
- **Root cause:** the ATR function reused a general EMA helper with the wrong smoothing weight.
- **Correction:** calculate the initial period average and apply Wilder smoothing to closed candles.
- **Prevention:** test named indicators against deterministic canonical sequences.

### 2026-08-13 — Left safety-loop lookups outside fail-closed boundaries

- **Impact:** a network failure could stop PANIC cancellation or time-stop inspection before a controlled HALT.
- **Root cause:** later mutation errors had handlers, but the first status lookups did not.
- **Correction:** PANIC and time-stop status reads now enter HALT and preserve uncertain order state.
- **Prevention:** test the first read and each recovery read in every safety loop.

### 2026-08-13 — Reconstructed selection configuration from one snapshot

- **Impact:** tick rounding could make repeated selection previews describe one strategy with different entry gaps.
- **Root cause:** the CLI derived a configuration parameter from a stored market price and rounded plan.
- **Correction:** resolve the gap from the same immutable table that creates the current SHADOW generation.
- **Prevention:** never reconstruct a configuration fingerprint from snapshot-dependent financial values.

### 2026-08-13 — Ended maker outcomes before the observed recovery

- **Impact:** version-ten classified late maker fills before their expected recovery completed.
- **Root cause:** the outcome horizon increased only to twice the entry lifetime without a production horizon-sensitivity replay.
- **Correction:** start a fresh cohort with 300-minute and 360-minute outcomes near the proven participation boundary.
- **Prevention:** replay several post-fill horizons before each experiment changes an entry lifetime.

### 2026-08-13 — Reconstructed a frozen rule from a dynamic price

- **Impact:** valid confirmation decisions could receive a false rule mismatch and remain permanently blocked.
- **Root cause:** validation derived the configured entry gap from a stored plan and a different snapshot price.
- **Correction:** use the immutable manifest gap while validating all other stored plan semantics.
- **Prevention:** reconstruct configuration fingerprints only from fields with the same provenance as the frozen rule.

### 2026-08-13 — Omitted a public version surface

- **Impact:** the first complete regression failed after the product version changed.
- **Root cause:** the initial patch updated the canonical version and changelog, but not the README version.
- **Correction:** synchronize the README and rerun the complete regression from the start.
- **Prevention:** search all version surfaces before the first release-candidate test run.

### 2026-08-13 — Mixed evaluated and retained confirmation windows

- **Impact:** later complete windows diluted three summary metrics from the frozen confirmation prefix.
- **Root cause:** numerators used evaluated windows, while denominators used all retained complete windows.
- **Correction:** derive both sides of each aggregate from the evaluated window count.
- **Prevention:** each cohort regression must add excluded evidence with an extreme opposing value.

### 2026-08-12 — Repeated a rejected zero-fill entry region

- **Impact:** every version-eight candidate recorded zero fills and could not measure absolute expectancy.
- **Root cause:** the next generation deepened entries without comparing its 40-basis-point boundary with version-four evidence.
- **Correction:** preserve version-eight evidence and move version nine to 34, 36, and 38 basis points.
- **Prevention:** compare all immutable generations before selecting a new experimental parameter range.

### 2026-08-12 — Repeated authentication alerts too frequently

- **Impact:** one continuing Binance rejection produced four similar Telegram notices in two hours.
- **Root cause:** the operator reminder reused a 30-minute infrastructure cooldown and included sanitized provider text.
- **Correction:** use a four-hour reminder and a fixed operator-focused reason without endpoint metadata.
- **Prevention:** keep automatic probe cadence independent from human reminder cadence and provider wording.

### 2026-08-12 — Used a credential-like documentation test name

- **Impact:** GitHub Actions blocked release 2.20.187 after all local release checks passed.
- **Root cause:** the new test name matched the external Lob credential detector pattern.
- **Correction:** shorten the test name and publish the correction as the direct next release.
- **Prevention:** keep test identifiers short and inspect external verified secret scan results before creating a release page.

### 2026-08-11 — Treated relative edge as sufficient experiment progress

- **Impact:** version-seven increased participation but every candidate retained a negative net expectancy confidence interval.
- **Root cause:** candidate selection emphasized fill rate and baseline edge before positive absolute expectancy.
- **Correction:** preserve version-seven evidence and test deeper version-eight entries with the corrected observation windows.
- **Prevention:** require positive absolute expectancy before promotion, even when a candidate beats its baseline.

### 2026-08-11 — Alerted on an incident level instead of its transition

- **Impact:** one public IP incident sent the same Telegram message during every minute-long authentication retry.
- **Root cause:** the notifier checked `public_ip_changed` as a level and used the generic metadata formatter without persistent alert identity.
- **Correction:** compare pending fingerprints, send one operator-focused notice, and send one notice after signed recovery.
- **Prevention:** persistent incident alerts must use durable transition identity and must exclude internal diagnostic fields from operator messages.

### 2026-08-10 — Ended one outcome at the entry deadline

- **Impact:** late version-six fills had no separate time to produce TP or STOP evidence.
- **Root cause:** the 60-minute outcome horizon equaled the longest permitted BUY lifetime.
- **Correction:** version-seven evaluates the 60-minute BUY lifetime through 90-minute and 120-minute outcomes.
- **Prevention:** require each entry experiment to retain a tested post-fill observation period.

### 2026-08-08 — Repeated a Git metadata permission failure

- **Impact:** the first staging command stopped without changing the index.
- **Root cause:** the command ignored the earlier branch-lock denial in the same workspace.
- **Correction:** rerun Git metadata writes with the required workspace permission.
- **Prevention:** after one Git lock denial, escalate every later metadata write in that task.

### 2026-08-08 — Updated only direct experiment tests

- **Impact:** the first complete regression run failed one supervisor integration count.
- **Root cause:** the search targeted v3 names and missed a generic decision-count assertion.
- **Correction:** update the integrated decision total for twelve version-four candidates.
- **Prevention:** search changed behavior and aggregate counts, not only renamed identifiers.

### 2026-08-08 — Guessed a release test path

- **Impact:** one focused verification command stopped before it ran the requested tests.
- **Root cause:** the command used an inferred filename instead of the repository test inventory.
- **Correction:** locate the release and version tests with `rg --files` before the rerun.
- **Prevention:** derive every focused test path from the current repository before execution.

### 2026-08-05 — Started a soak epoch before causal recovery

- **Impact:** the v2 stability denominator accumulated authentication-failure reconnect churn.
- **Root cause:** the epoch release preceded verified signed authentication and IP Guard recovery.
- **Correction:** preserve v2 and start v3 only after both authorities report recovery.
- **Prevention:** verify current external authority before each certification epoch change.

### 2026-08-05 — Started the alert cooldown before delivery

- **Impact:** Binance authentication failures produced no Telegram message.
- **Root cause:** services lacked injected configuration, and a failed send still started the success cooldown.
- **Correction:** inject the root-owned file through systemd and retain the actual delivery result.
- **Prevention:** alert tests must cover service configuration, failed transport, retry timing, and changing diagnostic endpoints.

### 2026-08-05 — Gated a runtime warning on deployment history

- **Impact:** the dashboard hid a current Binance authentication rejection.
- **Root cause:** the banner required `IP_BLOCKED` and a successful deployment record, while the runtime reported `AUTH_BACKOFF`.
- **Correction:** derive the warning from the fresh heartbeat and use an accurate message for each state.
- **Prevention:** current operational warnings must not depend on unrelated historical status records.

### 2026-08-04 — Resolved complete locks for one pinned package

- **Impact:** the first lock refresh stalled without changing either target lock.
- **Root cause:** a full resolver repeated work for a hash block already generated in another project lock.
- **Correction:** reuse the complete generated block, then validate each target with hashes and the dependency audit.
- **Prevention:** reuse an identical generated package block only when its version and source match exactly.

### 2026-08-04 — Used a recovery latch as a permanent alert gate

- **Impact:** repeated failed restarts produced no Telegram reminder after the first alert.
- **Root cause:** `health_alerted` controlled both recovery hysteresis and alert delivery.
- **Correction:** route every confirmed failure through the existing time-based alert gate.
- **Prevention:** delivery cooldowns and recovery-state latches must have separate responsibilities.

### 2026-08-03 — Used packet idleness as a network failure signal

- **Impact:** normal Wi-Fi traffic gaps produced frequent system warnings.
- **Root cause:** the hardware watchdog required received packets during every short interval.
- **Correction:** remove only the legacy `wlan0` interface check and keep reachability monitoring active.
- **Prevention:** network health checks must test reachability with hysteresis, not packet presence.

### 2026-08-03 — Left an obsolete timer outside release ownership

- **Impact:** systemd logged a failed statistics synchronization service every two minutes.
- **Root cause:** the replacement deployment removed the script but did not retire its legacy units.
- **Correction:** verified runtime asset installation now disables and removes the identified units.
- **Prevention:** each removed service script needs a tested unit-retirement step in the replacement release.

## Entry format

### YYYY-MM-DD — Short failure title

- **Impact:** what failed or became misleading.
- **Root cause:** the controllable reason the decision failed.
- **Correction:** what fixed the immediate problem.
- **Prevention:** the rule or test that must stop recurrence.

## Mistakes

### 2026-08-03 — Treated Testnet path overrides as optional

- **Impact:** a direct Testnet CLI run could retain Mainnet databases or control files.
- **Root cause:** the selector changed each path only when its Testnet variable was nonempty.
- **Correction:** resolve safe defaults, reject collisions, and apply all paths after validation.
- **Prevention:** venue switches must prove complete state isolation before changing process configuration.

### 2026-08-03 — Guessed every quote asset as four characters

- **Impact:** a transient metadata failure could hide a real balance for BTC-, ETH-, or BNB-quoted symbols.
- **Root cause:** the fallback encoded one suffix length instead of the exchange quote vocabulary.
- **Correction:** use the exact-accounting quote list and reject unknown suffixes.
- **Prevention:** symbol parsers must share one ordered quote vocabulary and test different suffix lengths.

### 2026-08-03 — Built indicators without connecting a consumer

- **Impact:** each fast-market worker received and processed unused candle data.
- **Root cause:** indicator production was implemented before its decision contract and remained after integration stopped.
- **Correction:** remove the candle subscription, calculations, state, and public snapshot fields.
- **Prevention:** each new stream and derived value must identify an active consumer and a decision test.

### 2026-08-03 — Latched a recoverable full-snapshot anomaly

- **Impact:** one duplicate or reordered depth snapshot could block fast-market BUY decisions until process restart.
- **Root cause:** full snapshots used permanent diff-stream sequence state that also survived reconnects.
- **Correction:** accept duplicates, recover after a valid snapshot, and reset connection-scoped evidence on reconnect.
- **Prevention:** stream tests must cover duplicate frames, reordered frames, recovery, and reconnect boundaries.

### 2026-08-03 — Trusted file order for OHLC construction

- **Impact:** an unsorted archive could silently assign incorrect minute open and close prices.
- **Root cause:** hash validation proved file integrity but not chronological semantics.
- **Correction:** reject the first aggregate trade whose timestamp decreases.
- **Prevention:** order-dependent aggregations must validate monotonic source keys before accumulation.

### 2026-08-03 — Applied one stream's synchronization gate to another stream

- **Impact:** aggregate trades received during depth synchronization disappeared from replay archives.
- **Root cause:** recording treated independent trade events as invalid until the depth sequence synchronized.
- **Correction:** buffer early trades within the event budget and flush them after depth proof.
- **Prevention:** mixed-stream tests must cover events before, during, and after synchronization.

### 2026-08-03 — Counted report paths instead of evidence identities

- **Impact:** repeated validation reports could satisfy the real-order coverage threshold.
- **Root cause:** readiness summed report aggregates without deduplicating their archive identity.
- **Correction:** block duplicate archive hashes and count one conservative report per archive.
- **Prevention:** every evidence aggregate must define and test its authoritative identity key.

### 2026-08-03 — Reused a cached test count after recording the same lesson

- **Impact:** the first candidate changelog overstated the main test count by five.
- **Root cause:** the count came from the pytest cache instead of the completed harness report.
- **Correction:** report the harness total and amend the same signed candidate.
- **Prevention:** never use `.pytest_cache` as evidence for a release test count.

### 2026-08-03 — Copied commission status allowlists into consumers

- **Impact:** replay calibration excluded valued legacy commissions from historical outcomes.
- **Root cause:** each consumer defined provenance validity with its own string set.
- **Correction:** move the recognized vocabulary to exact accounting and import its predicate.
- **Prevention:** financial consumers must not define independent commission status allowlists.

### 2026-08-02 — Escalated one unknown metric into total telemetry failure

- **Impact:** FIFO import evidence kept the supervisor in `RISK_PENDING` and stopped new SHADOW snapshots.
- **Root cause:** the streak reader raised a generic runtime error instead of returning structured uncertainty.
- **Correction:** keep the risk snapshot valid and block BUY through an explicit completeness field.
- **Prevention:** unavailable derived evidence must block its action without suppressing independent authoritative evidence.

### 2026-08-02 — Counted tests from a stale cache

- **Impact:** the first candidate changelog overstated the complete suite by five tests.
- **Root cause:** the count came from cached node identifiers instead of the completed test report.
- **Correction:** use the release harness count and amend the candidate before publication.
- **Prevention:** report test counts only from the completed command or signed verification manifest.

### 2026-08-02 — Added a verification field without a producer

- **Impact:** Pi verification could pass without checking account and inventory reconciliation.
- **Root cause:** the gate read a field that only the dashboard derived from human-readable text.
- **Correction:** publish exact structured evidence in the supervisor and block missing evidence.
- **Prevention:** contract tests must cover every producer and consumer of safety evidence.

### 2026-08-02 — Identified CI from Git topology alone

- **Impact:** a local or octopus merge could receive the release gate exception intended only for GitHub pull request CI.
- **Root cause:** the gate treated two or more parents as sufficient proof of a synthetic GitHub merge.
- **Correction:** require exact GitHub event evidence and authorize only the event's pull request head commit.
- **Prevention:** test every CI-only exception against local, malformed, wrong-parent, and multi-parent inputs.

### 2026-08-02 — Assumed every stored SELL had complete FIFO history

- **Impact:** the first complete test run rejected valid imported-basis and incomplete-symbol accounting scenarios.
- **Root cause:** the risk index treated missing derived lots as a trade failure instead of unavailable risk evidence.
- **Correction:** preserve accounting, mark only that symbol incomplete, and synchronize an applied cost-basis plan atomically.
- **Prevention:** derived risk tests must include imports, legacy gaps, and unrelated symbols with complete history.

### 2026-08-02 — Used a character class as a migration ceiling

- **Impact:** the first focused migration test applied migration 010 to a fixture intended to stop at 006.
- **Root cause:** the glob pattern constrained each digit but did not compare the complete migration number.
- **Correction:** parse each three-digit prefix and compare its integer value with the fixture boundary.
- **Prevention:** select migration ranges by parsed numeric versions, never by filename character classes.

### 2026-08-02 — Typed the GitHub repository name in a workflow command

- **Impact:** two read-only CI watch commands returned HTTP 404 and required a corrected rerun.
- **Root cause:** the command typed the repository owner instead of deriving it from the configured `origin`.
- **Correction:** rerun both watches with the canonical repository; both workflows reported success.
- **Prevention:** derive the complete repository name once from `origin` and reuse it for every `gh` command.

### 2026-08-01 — Added dashboard coverage to a capped test module

- **Impact:** the first complete test run failed the component test size gate.
- **Root cause:** the new regression was added before checking the existing 700-line limit.
- **Correction:** move the regression into a focused dashboard localization module.
- **Prevention:** check architecture budgets before adding tests to an existing component module.

### 2026-08-01 — Added a command without the command inventory

- **Impact:** the first complete test run failed one documentation contract.
- **Root cause:** the new CLI was documented in the runbook but omitted from the command reference.
- **Correction:** add `review_unattributed_fills` to the operator command table.
- **Prevention:** compare every new `bin` module with `docs/COMMAND_REFERENCE.md` before the full suite.

### 2026-08-01 — Guessed verification module names

- **Impact:** a successful full test sequence ended with a nonexistent module error.
- **Root cause:** the command used inferred names instead of the harness check definitions.
- **Correction:** use `bin.audit_numeric_boundaries` and `deploy/scan_tracked_secrets.py`.
- **Prevention:** copy verification commands from the harness specification before manual runs.

### 2026-08-01 — Deferred release surface and size checks

- **Impact:** the first full 2.20.119 test run failed three release contract tests.
- **Root cause:** the edit changed the version and guarded runtime before checking their linked constraints.
- **Correction:** synchronize README and compact the runtime without increasing its line count.
- **Prevention:** check version surfaces and monolith budgets before the first full test run.

### 2026-08-01 — Compared fixture paths by overlapping suffix

- **Impact:** the release rule test classified every unsafe fixture finding as a safe-file finding.
- **Root cause:** `unsafe_patterns.py` also ends with the text `safe_patterns.py`.
- **Correction:** compare the exact path name instead of a raw string suffix.
- **Prevention:** add a regression for filenames where one complete name is a suffix of another.

### 2026-08-01 — Reused a manually completed release SHA

- **Impact:** the first release command contained an unverified commit identifier and required replacement.
- **Root cause:** the command copied a short commit prefix and manually supplied the remaining characters.
- **Correction:** read the complete identifier directly with `git rev-parse HEAD`.
- **Prevention:** pass release identifiers only from command output or a validated shell variable.

### 2026-08-01 — Scanned an isolated tool environment as project source

- **Impact:** the English-source regression reported third-party package text as project violations.
- **Root cause:** the recursive source scan excluded `.venv` but not the new `.semgrep-venv` directory.
- **Correction:** exclude both isolated environments from repository source inspection.
- **Prevention:** every new local tool directory needs an ignore rule and a source-scan exclusion.

### 2026-08-01 — Mixed Semgrep with runtime-constrained audit tools

- **Impact:** the first lock compilation stopped on incompatible Click versions.
- **Root cause:** Semgrep was added to the environment constrained by the application CI lock.
- **Correction:** place Semgrep in a separate hashed environment and lock file.
- **Prevention:** inspect dependency constraints before adding development tools to a shared environment.

### 2026-08-01 — Left accepted IP telemetry stale

- **Impact:** IP Guard accepted the fingerprint, but heartbeat still showed the previous changed state.
- **Root cause:** the acceptance path persisted state without publishing the corresponding runtime update.
- **Correction:** publish `changed=false` immediately after authoritative acceptance.
- **Prevention:** recovery tests must compare persistent state with public runtime telemetry.

### 2026-08-01 — Invoked the Pi updater on the workstation

- **Impact:** one command stopped at local sudo before any deployment change.
- **Root cause:** the updater command omitted the required SSH execution boundary.
- **Correction:** run the exact updater inside the Raspberry Pi checkout through SSH.
- **Prevention:** identify the command host explicitly before each deployment command.

### 2026-08-01 — Grew the supervisor during an IP Guard fix

- **Impact:** the first focused run failed the supervisor non-growth gate.
- **Root cause:** the final consensus branch used one line beyond the exact budget.
- **Correction:** compact the internal function signature without raising the budget.
- **Prevention:** measure each guarded monolith before its first focused test run.

### 2026-08-01 — Staged without the Git metadata permission

- **Impact:** the first staging command stopped before it changed the index.
- **Root cause:** the command ignored the active read-only permission for `.git`.
- **Correction:** request the narrow Git staging permission and repeat the command.
- **Prevention:** inspect Git metadata permissions before each staging operation.

### 2026-08-01 — Grew the dashboard runtime during a resilience fix

- **Impact:** the first complete test run failed the monolith non-growth gate.
- **Root cause:** the new HTTP 429 response used four lines beyond the exact budget.
- **Correction:** keep the response compact without increasing the architecture limit.
- **Prevention:** check line budgets before each edit to a listed runtime monolith.

### 2026-08-01 — Blocked SQLite WAL coordination in the dashboard sandbox

- **Impact:** dashboard database routes returned HTTP 503 while healthy routes remained available.
- **Root cause:** the service made the database directory read-only, which blocked SQLite shared-memory sidecars.
- **Correction:** permit directory coordination while connections remain `mode=ro` and query-only.
- **Prevention:** every live WAL reader must have a sandbox test for sidecar coordination.

### 2026-08-01 — Checked the source dashboard unit name on the Pi

- **Impact:** the first diagnostic incorrectly reported that the dashboard service was inactive.
- **Root cause:** the command used `pi-dashboard`, but deployment installs the unit as `pi-healthd`.
- **Correction:** resolve the deployed unit name from installation scripts before service inspection.
- **Prevention:** derive service diagnostics from deployed asset contracts, not source filenames.

### 2026-08-01 — Built a release command with an unquoted interpreter path

- **Impact:** the first clean-worktree release command did not start the harness.
- **Root cause:** the interpreter path contained a space, and the command also used a manually completed SHA.
- **Correction:** quote the project interpreter path and read the exact SHA with `git rev-parse HEAD`.
- **Prevention:** every release command must use the project interpreter and exact SHA from commands, without manual path or SHA construction.

### 2026-08-01 — Used fragile inline quoting for a remote database audit

- **Impact:** two read-only audit commands failed before they opened a database.
- **Root cause:** a multi-statement Python program passed through nested local and remote shell quoting.
- **Correction:** send one checked read-only script to remote Python through standard input.
- **Prevention:** use a temporary reviewed script for multi-statement remote diagnostics; do not use complex SSH one-liners.

### 2026-08-01 — Used a non-filling price outside exchange filters

- **Impact:** the controlled Testnet drill connected and reconnected, but
  Binance rejected its order before an authenticated order event existed.
- **Root cause:** the reused smoke builder placed a LIMIT BUY fifty percent
  below market without checking the percent-price filter.
- **Correction:** use `LIMIT_MAKER` one percent below the current price and
  retain the notional ceiling and confirmed cleanup.
- **Prevention:** every exchange drill order must prove both non-taking behavior
  and compliance with current symbol filters.

### 2026-08-01 — Allowed a signed Testnet URL into a traceback

- **Impact:** a rejected Testnet mutation printed a short-lived request
  signature in local diagnostic output.
- **Root cause:** the drill used `requests.raise_for_status()`, whose default
  exception message includes the complete prepared URL.
- **Correction:** replace the default exception with a bounded error that keeps
  only HTTP status, Binance code, exception class, and endpoint path.
- **Prevention:** every signed HTTP client must have a regression that rejects
  URLs, query parameters, signatures, keys, and secrets in exception text.

### 2026-08-01 — Repeated manual expansion of a release SHA

- **Impact:** one release harness ran with a false expected SHA and was stopped before it created an artifact.
- **Root cause:** the command expanded the short commit display manually instead of reading `git rev-parse HEAD`.
- **Correction:** amend the learning record, read the new exact SHA, and pass that value without manual transcription.
- **Prevention:** assign the final `git rev-parse HEAD` output to the release command in one shell invocation.

### 2026-08-01 — Waited for post-preflight state during deployment

- **Impact:** the Pi installed a valid release, but its updater reported failure after 120 seconds.
- **Root cause:** the supervisor published safe readiness only after authenticated preflight and market initialization.
- **Correction:** publish fail-closed `RISK_PENDING` before preflight and recognize that state in the updater.
- **Prevention:** deployment tests must prove one accepted fail-closed heartbeat exists before every slow startup boundary.

### 2026-07-31 — Described a daily artifact as current

- **Impact:** Star History displayed one star after GitHub already reported two.
- **Root cause:** the workflow used only one daily schedule and no star event.
- **Correction:** add the new-star event and hourly authoritative reconciliation.
- **Prevention:** match freshness claims with source events and a bounded reconciliation interval.

### 2026-07-31 — Documented obsolete backtest options

- **Impact:** the README showed commands that the current backtest parser rejects.
- **Root cause:** the shortened README was not compared with the command parser.
- **Correction:** use the positional CSV argument and the current `--archive` option.
- **Prevention:** derive CLI examples from parser help and test important documentation contracts.

### 2026-07-31 — Inserted prose before an existing sentence continuation

- **Impact:** the first documentation check showed a duplicated continuation
  that made the AI-mode paragraph grammatically invalid.
- **Root cause:** the patch matched the first wrapped line of a sentence but did
  not replace its complete original paragraph.
- **Correction:** rewrite the whole paragraph as one coherent mode, backoff and
  evidence contract.
- **Prevention:** after patching wrapped prose, read the complete surrounding
  paragraph rather than relying only on patch application and test success.

### 2026-07-31 — Sanitized trusted local validation reasons with provider errors

- **Impact:** the first focused advisory run hid the safe `byte limit` reason
  from two existing regressions, making an intentional response-size rejection
  less actionable to an operator.
- **Root cause:** one sanitizer reduced every caught exception to its class even
  though local bounded-response validators have fixed, non-provider messages.
- **Correction:** preserve only an explicit allowlist of local response
  validation reasons while continuing to remove network URL and body text.
- **Prevention:** diagnostic sanitizers must classify trusted local validation
  failures separately from untrusted transport and payload exceptions.

### 2026-07-31 — Assumed dashboard lifespan would not collect during an API test

- **Impact:** the first focused chart run failed two new assertions even though
  the endpoint returned correctly aligned exact and unavailable series.
- **Root cause:** the tests expected one immutable metrics row while
  `TestClient` correctly started the application lifespan collector, which
  appended current host samples to the isolated history file.
- **Correction:** assert value semantics and equal series lengths independently
  of the number of samples collected during the request.
- **Prevention:** dashboard API tests that start the lifespan must either stub
  the collector explicitly or treat its additional telemetry rows as normal.

### 2026-07-29 — Applied a lifetime failure count to a bounded soak

- **Impact:** after fixing pending horizons, 26 immutable historical
  expirations still made every new 24-hour run fail before it began.
- **Root cause:** the audit counted terminal rows across the lifetime database
  but measured duration from the current process start.
- **Correction:** expose the lifetime count separately and gate only
  expirations created inside the authoritative soak window.
- **Prevention:** every bounded audit must apply one explicit time cutoff to
  each historical failure metric while retaining carried active backlog.

### 2026-07-29 — Treated all in-flight horizons as a processing backlog

- **Impact:** production soak approval could never pass while continuous
  SHADOW collection correctly kept future 1/5/15-minute outcomes pending.
- **Root cause:** the audit used `pending == 0` without comparing each outcome's
  eligibility time with the report cutoff or allowing bounded settlement time.
- **Correction:** classify future, settling, overdue and unrecovered expired
  outcomes separately; only the latter two block approval.
- **Prevention:** streaming approval tests must include simultaneous future
  work and separately prove that overdue and expired evidence fails closed.

### 2026-07-29 — Replaced a specific prediction-store error contract

- **Impact:** the first focused experiment run failed one existing re-anchor
  regression even though persistence safety remained intact.
- **Root cause:** a shared counterfactual baseline check replaced the established
  re-anchor-specific diagnostic while adding experiment kinds.
- **Correction:** preserve the exact re-anchor contract and use a separate
  explicit-baseline diagnostic for experiment records.
- **Prevention:** when extending a validator to new variants, retain existing
  branch-specific messages and run the original contract tests immediately.

### 2026-07-29 — Relied on executescript for crash-sensitive migrations

- **Impact:** a power loss between DDL statements or before the separate version
  insert could leave a Raspberry Pi database partially migrated and unable to
  complete startup automatically.
- **Root cause:** migration files and completion evidence were treated as one
  logical operation, but `sqlite3.executescript` supplied implicit commit
  boundaries and bootstrap used another connection.
- **Correction:** execute parser-complete statements inside a runner-owned
  transaction, record the version there, couple bootstrap to its completion
  marker, and guard exact legacy column resumes.
- **Prevention:** every migration test suite must inject failures after schema
  writes and at completion-evidence writes, and duplicate versions must fail
  before any database mutation.

### 2026-07-29 — Added lifecycle policy back into a guarded monolith

- **Impact:** the first complete suite failed architecture budgets even though
  functional lifecycle tests passed, delaying the release without changing
  runtime or external state.
- **Root cause:** signal and restart orchestration were initially implemented
  in `supervision/runtime.py` and new tests in `test_safety_gates.py` instead of
  their existing component boundaries.
- **Correction:** move registry, signal and rolling-window policy into
  `supervision/process_manager.py`, move tests into
  `tests/supervision/test_process_manager.py`, and keep both guarded monoliths
  at or below their prior limits.
- **Prevention:** check architecture line budgets before the first full suite;
  new lifecycle policy belongs to its package component, never the integration
  runtime or a legacy aggregate test module.

### 2026-07-29 — Selected a focused pytest node without resolving its name

- **Impact:** the first focused verification command stopped at collection and
  had to be rerun; no test or repository state was changed.
- **Root cause:** the intended re-anchor test name was inferred instead of read
  from the test module before constructing the node ID.
- **Correction:** resolve the exact function with `rg` and rerun the focused
  set using the discovered node.
- **Prevention:** never type a pytest node from memory; discover its exact
  module and function name before starting a selective run.

### 2026-07-29 — Split graceful shutdown authority across incompatible layers

- **Impact:** a normal service stop could terminate the supervisor immediately,
  leave workers unsupervised until SIGKILL and turn every deployment stop into
  an avoidable recovery exercise; slower crash loops could also restart without
  backoff or alert.
- **Root cause:** worker TERM handling, supervisor cleanup, systemd kill mode and
  restart counters were each reviewed locally without an end-to-end lifecycle
  test across their boundaries.
- **Correction:** handle supervisor TERM, signal the full control group, track
  non-zero exits in a rolling window and alert at a bounded threshold.
- **Prevention:** service lifecycle regressions must verify the complete signal
  route, STOPPING evidence, child exit, escalation timeout and both fast and
  slow repeated failures.

### 2026-07-29 — Reused a signed-value formatter for an expense magnitude

- **Impact:** the Telegram digest displayed fees as positive income even though
  exact net PnL correctly treated them as a cost.
- **Root cause:** presentation reused the generic money formatter without
  converting the non-negative stored fee magnitude into signed account impact.
- **Correction:** negate fees only at the digest presentation boundary and
  retain the positive exact accounting value.
- **Prevention:** financial-report tests must assert the displayed sign of every
  income and expense category, not only its rounded magnitude.

### 2026-07-29 — Treated service inactivity as restart authorization

- **Impact:** the watchdog could restart a service that an operator stopped.
  Process arguments exposed Telegram secrets.
  Stale alerts had no limit.
  A missing route caused a probe of an invented gateway.
- **Root cause:** watchdog recovery inferred operator intent and network
  topology from convenient defaults instead of requiring explicit systemd,
  descriptor and route evidence.
- **Correction:** require the unit to remain enabled immediately before
  restart, keep Telegram data off argv, enforce outbox TTL/CAP retention and
  report absent routes directly.
- **Prevention:** watchdog regressions must prove intentional-stop suppression,
  secret-free process arguments, bounded durable queues and no guessed network
  endpoint.

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

### 2026-08-01 — Documented the transient stream path after persistence changed

- **Impact:** the Pi verification example read `/run`, while the service stored durable stream evidence under `/var/lib`.
- **Root cause:** the service path changed, but the operator command was not covered by a documentation contract test.
- **Correction:** use the persistent path in the Pi guide and verification examples.
- **Prevention:** tests must compare every documented evidence path with the deployed service configuration.

### 2026-08-01 — Tested the drill with injected paths only

- **Impact:** release 2.20.123 rejected the real persistent HALT before any exchange mutation.
- **Root cause:** tests supplied explicit temporary paths, but the operator CLI did not inherit systemd path overrides.
- **Correction:** resolve existing persistent Pi paths from any runtime mapping while preserving explicit paths.
- **Prevention:** every operator command must have a Pi-default integration test without systemd environment variables.

### 2026-08-01 — Typed a release SHA instead of resolving it

- **Impact:** the first commit-signature check failed before release verification.
- **Root cause:** the verification command used a manually copied full SHA.
- **Correction:** resolve the candidate with `git rev-parse HEAD` in the same command.
- **Prevention:** never type a release SHA when Git can provide the exact value.

### 2026-08-03 — Copied an account fee default into separate consumers

- **Impact:** default breakeven protection could close below the actual round-trip fee floor.
- **Root cause:** lifecycle and dashboard code assumed a BNB discount independently from execution code.
- **Correction:** all active consumers import one conservative exact fee constant.
- **Prevention:** define each financial default once, and require explicit configuration for any discount.

### 2026-08-03 — Omitted the stopped-runtime gate from accounting retirement

- **Impact:** a live writer could invalidate the audit or receive a database-lock error during retirement.
- **Root cause:** the new CLI copied confirmation and backup gates, but missed the shared runtime gate.
- **Correction:** APPLY now checks stopped-runtime evidence before it calls the irreversible operation.
- **Prevention:** every destructive CLI needs a test that blocks before its first mutation boundary.

### 2026-08-03 — Retained float planners after Decimal migration

- **Impact:** an unused parallel monetary API could be selected during later refactoring.
- **Root cause:** callers migrated to Decimal, but the replaced implementation and tests remained.
- **Correction:** remove the float API and keep only exact planning functions.
- **Prevention:** finish each financial type migration with a dead-API audit and removal regression.

### 2026-08-03 — Used process age as User Stream stability evidence

- **Impact:** repeated reconnects could accumulate the same readiness duration as one stable connection.
- **Root cause:** the audit checked the monotonic counters independently, without a reconnect-rate limit.
- **Correction:** calculate cumulative reconnects per observed hour and block excessive churn.
- **Prevention:** each soak gate must bound failure frequency, not only total elapsed time.

### 2026-08-03 — Used lifetime counters for a repeatable soak

- **Impact:** repaired transport behavior could never pass while old reconnects remained in evidence.
- **Root cause:** the readiness denominator had no reviewed epoch boundary.
- **Correction:** preserve lifetime counters and subtract an immutable baseline for the current soak.
- **Prevention:** repeatable certification needs append-only epochs, not counter resets or lifetime-only ratios.

### 2026-08-03 — Put host-specific maintenance in the product updater

- **Impact:** one release coupled Ladder Dragon deployment to unrelated `atop` and `rtl_tcp` services.
- **Root cause:** a global failed-unit scan was mistaken for the requested bot log review.
- **Correction:** remove all unrelated service management and keep the local host correction separate.
- **Prevention:** change a non-project service only through an explicit host-maintenance task.

### 2026-08-03 — Repeated manual release SHA reconstruction

- **Impact:** the release harness completed but blocked because its expected SHA was incorrect.
- **Root cause:** a short commit identifier was expanded manually instead of read from Git.
- **Correction:** amend the candidate and resolve `HEAD` inside the harness command.
- **Prevention:** never type or reconstruct a release SHA; use `git rev-parse HEAD` in the same shell command.
### 2026-08-04 — Described an ambiguous Binance rejection as an IP block

- **Impact:** the operator looked for an IP block that Binance did not report.
- **Root cause:** status text treated code `-2015` as proof of one cause, although it also covers keys and permissions.
- **Correction:** use accurate signed-authentication wording and retry changed-IP recovery each minute.
- **Prevention:** user-facing diagnostics must not narrow a provider error beyond its documented meaning.

### 2026-08-05 — Released a soak requirement without its production control

- **Impact:** a stable Mainnet observer could not produce the controlled reconnect required by the Pi profile.
- **Root cause:** the Testnet drill owned reconnect control, while the Mainnet drill only proved order event to REST behavior.
- **Correction:** add a signal-safe reconnect request to the persistent shadow service.
- **Prevention:** every mandatory verification condition needs a documented production command before release.

### 2026-08-06 — Counted expected socket renewal as instability

- **Impact:** 111 idle reconnects blocked a stream with zero transport failures.
- **Root cause:** readiness used the total reconnect counter after the observer added explicit reconnect classifications.
- **Correction:** gate only `transport_failure_reconnects` and keep all counters visible.
- **Prevention:** reliability gates must use classified failure counters, not aggregate lifecycle counters.

### 2026-08-06 — Restarted a responsive fail-closed supervisor

- **Impact:** temporary exchange timeouts broke the required continuous production soak window.
- **Root cause:** the watchdog accepted preflight backoff but omitted the fresh `RISK_PENDING` heartbeat.
- **Correction:** accept `RISK_PENDING` while its heartbeat remains fresh.
- **Prevention:** each new runtime state needs an end-to-end watchdog policy test before release.

### 2026-08-06 — Left two assertions on the previous epoch index

- **Impact:** the first focused test run failed after the v4 fixture correctly added a fourth epoch.
- **Root cause:** most assertions moved to index three, but two retained the old index.
- **Correction:** verify the new baseline fields on the complete current epoch object.
- **Prevention:** after inserting ordered fixture data, review every positional assertion in that test.

### 2026-08-08 — Used an unbounded temporary sort for SHADOW reports

- **Impact:** the Pi kept source evidence but stopped publishing current prediction summaries.
- **Root cause:** report queries sorted the complete append-only database in the small temporary filesystem.
- **Correction:** use append order and a bounded recent decision window for derived analytics.
- **Prevention:** test every growing operational query for bounded memory and temporary-storage use.

### 2026-08-08 — Duplicated Binance clock handling in the dashboard

- **Impact:** a clock drift could reject read-only dashboard requests while trading reads recovered.
- **Root cause:** the dashboard signed requests with local time and did not handle `-1021`.
- **Correction:** use the shared midpoint offset calculation and one resynchronized retry.
- **Prevention:** share exchange time primitives across every signed transport.

### 2026-08-08 — Substituted current price for missing history

- **Impact:** portfolio change could hide price movement when an exact historical candle was unavailable.
- **Root cause:** a display fallback treated current price as historical evidence.
- **Correction:** require the exact minute and return an unavailable portfolio change otherwise.
- **Prevention:** never replace missing historical data with later data in a time-based metric.

### 2026-08-08 — Inferred backup success from an archive name

- **Impact:** the dashboard could show success for a partial archive or stale backup attempt.
- **Root cause:** status and archive identity were independent, and the archive fallback was optimistic.
- **Correction:** publish verified archives atomically and require matching status identity before success.
- **Prevention:** artifact health must use completion evidence that identifies the exact published artifact.

### 2026-08-08 — Used a credential-like test identifier

- **Impact:** the verified secret scan blocked the first release candidate.
- **Root cause:** a long test name matched the Lob test credential detector.
- **Correction:** shorten the test name and keep the verified detector enabled.
- **Prevention:** run the verified remote secret scan before any production deployment.

### 2026-08-08 — Kept REAL affinity in unresolved-fill evidence

- **Impact:** SQLite converted exact incident strings to IEEE-754 values in compatibility columns.
- **Root cause:** the exact-text migration added companion columns but retained the original REAL declarations.
- **Correction:** migrate both compatibility and companion columns to equal exact TEXT values.
- **Prevention:** finish each exact-money migration with storage-affinity and direct-reader tests.

### 2026-08-08 — Assumed one SQLite legacy-float rendering

- **Impact:** the release profile blocked and exposed a non-round-trip legacy value on an older SQLite version.
- **Root cause:** the first migration used SQLite `printf('%.17g')` and expected identical behavior across versions.
- **Correction:** use Python 17-digit formatting and verify equal TEXT values plus exact legacy round-trip behavior.
- **Prevention:** run migration tests with the project virtual environment before the release profile.

### 2026-08-08 — Encoded unknown AI slippage as zero

- **Impact:** retroactively linked fills could overstate net PnL and opportunity cost.
- **Root cause:** the linkage schema had no provenance field for an unavailable expected price.
- **Correction:** add slippage provenance and exclude incomplete financial evidence from approval consumers.
- **Prevention:** every optional financial input must distinguish unavailable data from a verified zero.

### 2026-08-08 — Stored current price as historical settlement

- **Impact:** a transient lookup failure could create permanent, incorrect predictor labels.
- **Root cause:** exception handling replaced unavailable historical evidence with the current cycle price.
- **Correction:** keep the horizon pending and retry the authoritative lookup during a later cycle.
- **Prevention:** never persist a fallback value as time-bound ground truth without explicit provenance.

### 2026-08-08 — Allowed partial exchange fill identity

- **Impact:** repeated fills without `trade_id` could duplicate AI PnL evidence.
- **Root cause:** AI deduplication treated the Binance trade identifier as optional.
- **Correction:** require both exchange identifiers before ledger or AI database mutation.
- **Prevention:** reject financial events that lack their authoritative deduplication identity.

### 2026-08-08 — Marked blocked retention as systemd success

- **Impact:** repeated backup-gated retention blocks were absent from failed-unit monitoring.
- **Root cause:** the unit included the CLI BLOCKED exit in `SuccessExitStatus`.
- **Correction:** accept only exit code `0` as service success.
- **Prevention:** never whitelist a fail-closed maintenance result as successful execution.

### 2026-08-08 — Replaced malformed ladder input with hidden defaults

- **Impact:** LIVE workers could receive economic parameters that the operator did not select.
- **Root cause:** the plan runner caught parse failures and substituted hard-coded percentages.
- **Correction:** validate the full ladder argument before network access or worker launch.
- **Prevention:** reject malformed execution parameters instead of selecting fallback values.

### 2026-08-08 — Allowed SQLite END through the migration guard

- **Impact:** a future migration could commit schema changes before recording its version.
- **Root cause:** the transaction-control expression recognized only `END TRANSACTION`.
- **Correction:** reject standalone `END` while preserving complete trigger statements.
- **Prevention:** test every SQLite transaction-control alias against the script boundary.

### 2026-08-08 — Let transport middleware change the security peer

- **Impact:** application checks could not distinguish the socket peer from a forwarded client address.
- **Root cause:** Uvicorn parsed forwarding headers before the application authenticated nginx.
- **Correction:** preserve the socket peer and parse one client header after proxy authentication.
- **Prevention:** authenticate a proxy before accepting any security-sensitive forwarded identity.

### 2026-08-08 — Added security tests to a full presentation module

- **Impact:** the complete regression stopped at the component size gate.
- **Root cause:** the first patch did not check the destination test module budget.
- **Correction:** move proxy security tests into a focused component module.
- **Prevention:** check architecture budgets before adding tests to an established component.

### 2026-08-10 — Compared lifetimes beyond the observation horizon

- **Impact:** version-four and version-five TTL pairs produced identical evidence and delayed useful learning.
- **Root cause:** candidate lifetimes exceeded the fixed 15-minute maximum outcome horizon.
- **Correction:** give version-six candidates isolated 30-minute and 60-minute outcome horizons.
- **Prevention:** prove that each experimental parameter can change an outcome inside its observation window.

### 2026-08-12 — Coupled confirmation reporting to lifecycle mutation

- **Impact:** a dashboard read could finalize an experiment, while part of its inference still used dependent snapshots.
- **Root cause:** the first protocol reused the snapshot gate and changed state inside the report function.
- **Correction:** use block-native inference and require explicit finalization of one reviewed report fingerprint.
- **Prevention:** keep reporting read-only and define the independent statistical unit before implementation.

### 2026-08-13 — Limited minimum-notional repair to compatibility filters

- **Impact:** refreshed production filters could suppress an otherwise valid LIMIT BUY level.
- **Root cause:** the final quantity repair was conditional on missing exact filters.
- **Correction:** apply exact ceiling repair to BUY orders within the approved quote budget.
- **Prevention:** test exchange-rule changes at the final mutation boundary with production filter fields.

### 2026-08-13 — Left initial reconciliation outside network boundaries

- **Impact:** MARKET, OCO, OTOCO, and BUY protection retries could lose their controlled uncertainty response.
- **Root cause:** exception handling covered submissions and later verification but not each function's first exchange lookup.
- **Correction:** centralize active-intent reconciliation and halt protection when BUY status is unavailable.
- **Prevention:** include the first network operation in every mutation and protection failure checklist.

### 2026-08-14 — Presented multi-symbol SHADOW as one experiment

- **Impact:** the dashboard hid mature SOLUSDT evidence and showed ETHUSDT execution-only errors.
- **Root cause:** presentation selected the first symbol, while supervision applied controls before checking execution scope.
- **Correction:** render each symbol separately and mark execution-only controls not applicable for SHADOW-only symbols.
- **Prevention:** test every multi-symbol view and control with distinct execution and observation scopes.

### 2026-08-17 — Enlarged the legacy supervisor coordinator

- **Impact:** the first promotion patch failed the runtime size budget.
- **Root cause:** initialization and promotion orchestration were added before checking the coordinator limit.
- **Correction:** extract SHADOW initialization and promotion gates into focused modules.
- **Prevention:** inspect architecture budgets before changing a known runtime coordinator.

### 2026-08-17 — Reused a model window as statistical history

- **Impact:** selection and control gates could never reach 120 independent observations.
- **Root cause:** one 1,000-row limit served both model training and long-horizon inference.
- **Correction:** keep bounded model history and stream independent statistical timestamps from full history.
- **Prevention:** calculate maximum attainable independent samples before starting each experiment.

### 2026-08-17 — Checked inventory CAP only before order planning

- **Impact:** one accepted BUY could move symbol exposure above its absolute CAP.
- **Root cause:** the Risk Manager compared current exposure without reserving the proposed order.
- **Correction:** clamp batch budgets and recheck authoritative inventory immediately before POST.
- **Prevention:** test each absolute CAP with exposure just below its boundary and a larger proposed mutation.

### 2026-08-18 — Continued a BUY batch after uncertain submission

- **Impact:** a later BUY could be submitted before the accepted quantity of the first BUY was known.
- **Root cause:** the batch treated all placement exceptions as level-local failures.
- **Correction:** raise a typed uncertainty for LIMIT and OTOCO, then stop the batch immediately.
- **Prevention:** test that a lost acknowledgement permits exactly one mutation attempt per batch.

### 2026-08-18 — Counted horizons as training samples

- **Impact:** adding outcome horizons shortened cold-start training without adding independent market information.
- **Root cause:** the walk-forward counter advanced for each resolved row instead of each decision timestamp.
- **Correction:** purge overlapping timestamps and count each retained timestamp once.
- **Prevention:** define the statistical unit before setting every sample threshold.

### 2026-08-18 — Mixed binding and no-op control evidence

- **Impact:** unchanged plans could dilute an effect estimate or appear to support control promotion.
- **Root cause:** control records did not state whether the candidate changed the baseline plan.
- **Correction:** store exact binding metadata and evaluate binding and full cohorts separately.
- **Prevention:** every counterfactual control record must identify its changed field and pre-outcome reason.

### 2026-08-19 — Moved shared cancellation evidence too narrowly

- **Impact:** two re-anchor tests lost their injectable order-lifetime evidence boundary.
- **Root cause:** cleanup extraction removed a helper before checking its re-anchor caller.
- **Correction:** retain a thin supervisor wrapper around the shared cleanup implementation.
- **Prevention:** search every caller before moving a private helper, then run the complete suite.

### 2026-08-19 — Described all candidate exits as maker orders

- **Impact:** statistical confirmation could imply executable profit without modeling stop-limit non-fill risk.
- **Root cause:** the candidate rule copied the maker entry label to the complete OCO exit.
- **Correction:** identify each OCO leg and block promotion for the incomplete candle-touch execution model.
- **Prevention:** compare every evidence order type with the exact production exchange request before enabling promotion.

### 2026-08-19 — Re-entered exposure limits after CHAMPION preview

- **Impact:** activation could use larger caps than the operator reviewed.
- **Root cause:** the reviewed artifacts excluded limits, and activation constructed a new policy from CLI values.
- **Correction:** expose the complete policy fingerprint and require it unchanged during activation.
- **Prevention:** bind every reviewed mutable input to one saved or fingerprinted activation artifact.

### 2026-08-20 — Treated incompatible history as fixed-rule training

- **Impact:** old candidate rows appeared to shorten cold-start time but could not validate the new execution rule.
- **Root cause:** an empty compatibility filter removed the candidate-kind restriction.
- **Correction:** return zero compatible history and remove training from the fixed promotion rule.
- **Prevention:** require an explicit compatibility identity before historical evidence enters any statistical role.

### 2026-08-22 — Sampled depth independently from validation mutations

- **Impact:** no terminal Mainnet order had full depth coverage for replay validation.
- **Root cause:** the hourly recorder schedule was not bound to the complete order lifecycle.
- **Correction:** run a bounded continuous archive from pre-POST readiness through terminal cleanup.
- **Prevention:** test that every empirical outcome interval is contained in exactly one source archive.

### 2026-08-22 — Evaluated episode evidence with local thresholds

- **Impact:** a candidate could pass a test that differed from its frozen manifest fingerprint.
- **Root cause:** the evaluator retained constants after lifecycle manifests became authoritative.
- **Correction:** evaluate only a validated manifest contract and block every unsupported legacy contract.
- **Prevention:** test each frozen threshold at the evaluator boundary and compare the complete canonical contract.

### 2026-08-22 — Froze regime evidence at a partial statistical pass

- **Impact:** later regime episodes could not repair coverage after an early sign-test boundary.
- **Root cause:** the code stored `passed_at` before all combined gates passed.
- **Correction:** freeze the boundary only after statistics, fills, drawdown, and regime gates pass together.
- **Prevention:** test that later looks can repair incomplete regime coverage.

### 2026-08-22 — Excluded protective exits from strategy expectancy

- **Impact:** six profitable take-profits hid a negative result after nine PANIC flatten exits.
- **Root cause:** PANIC was classified only as a safety veto, outside promotion eligibility.
- **Correction:** include PANIC flatten PnL and count PANIC vetoes as terminal unfilled attempts.
- **Prevention:** reconcile every terminal execution reason with the statistical trial definition.

### 2026-08-22 — Omitted the new evaluator from report dispatch

- **Impact:** the version 19 report failed closed before it could evaluate any live episode.
- **Root cause:** the dispatch allowlist omitted the new statistical method identifier.
- **Correction:** route version 19 manifests to the episode evaluator.
- **Prevention:** test each frozen statistical method through the public report entry point.

### 2026-08-24 — Counted a blocked entry regime as promotion evidence

- **Impact:** profitable RECOVERY episodes made version 19 look positive while its executable regimes remained negative.
- **Root cause:** the collector excluded PANIC but did not share the CHAMPION entry-regime allowlist.
- **Correction:** preserve version 19 as pilot evidence and start version 20 only in executable regimes.
- **Prevention:** fingerprint the entry-state scope and reject every result outside that scope.

### 2026-08-24 — Added proof during replay import

- **Impact:** a generic drill report could appear to validate candidate parameters it never exercised.
- **Root cause:** the importer stamped its expected candidate domain onto the source report.
- **Correction:** require a source-owned reusable engine domain and keep candidate expectancy in SHADOW evidence.
- **Prevention:** importers can verify proof fields but must never create missing proof.

### 2026-08-24 — Allowed activation above the observed evidence scale

- **Impact:** the first CHAMPION could accept more inventory than its live evidence covered.
- **Root cause:** preview limits were fingerprinted but were not bounded by the evidence notional.
- **Correction:** require exact 6 USDT caps, one managed position, and one closed probation lifecycle.
- **Prevention:** bind first-production scale to observed evidence before fingerprinting operator limits.

### 2026-08-25 — Let replay callers select acceptance evidence

- **Impact:** weaker CLI thresholds or omitted sessions could produce a misleading replay PASS.
- **Root cause:** report generation owned thresholds and session selection without an immutable batch identity.
- **Correction:** fingerprint the production policy and bind import to every batch archive and order.
- **Prevention:** recompute every imported PASS from immutable source evidence and a built-in policy.

### 2026-08-25 — Counted reservations as completed validation attempts

- **Impact:** a resumed batch could skip an uncertain mutation and continue with another real order.
- **Root cause:** the ledger stored reservations only and the runner counted physical rows.
- **Correction:** add authenticated terminal transitions and permanently close uncertain batches.
- **Prevention:** durable mutation workflows must distinguish reservation, success, and uncertainty.

### 2026-08-25 — Omitted version 22 from report dispatch

- **Impact:** a new empty version 22 experiment reported a legacy-criteria error instead of normal progress.
- **Root cause:** the manifest test did not call the public report entry point for the new statistical method.
- **Correction:** register the version 22 method and test the complete report path before release.
- **Prevention:** each new statistical method must pass a public empty-evidence report test.

### 2026-08-26 — Skipped immediate narrow validation while editing diagnostics

- **Impact:** focused diagnostic tests failed twice before release; deployed code was not affected.
- **Root cause:** a broad replacement changed a helper, and a test used an undefined module constant.
- **Correction:** restore the helper variable and use an explicit decimal in the test.
- **Prevention:** use function-specific patch context and run the exact test after each mechanical edit.

### 2026-08-26 — Imported L2 before diagnostics could become complete

- **Impact:** valid retained archives never attached to matching six-hour entry paths.
- **Root cause:** the importer ran once when each archive ended, before diagnostic maturity.
- **Correction:** rescan retained metadata and validate only archives covering complete unfeatured paths.
- **Prevention:** test joins where source artifacts and derived records mature in different cycles.

### 2026-08-26 — Generated positive thresholds for a downside veto

- **Impact:** future candidate selection could classify ordinary pre-fill movement as adverse decline.
- **Root cause:** candidate identifiers used absolute magnitudes, and those magnitudes also entered the threshold field.
- **Correction:** keep positive identifiers but emit negative basis-point thresholds.
- **Prevention:** assert the sign and safe range of every generated financial threshold.

### 2026-08-27 — Coupled public capture to completed-file processing

- **Impact:** rotation created gaps that prevented continuous historical policy replay.
- **Root cause:** each file closed its connection before calibration and diagnostic import completed.
- **Correction:** retain one connection and book across verified segments, with a separate processing child.
- **Prevention:** test sequence continuity and exactly-once events across multiple rotations.

### 2026-08-27 — Replayed known fills instead of future policy opportunities

- **Impact:** cancellation comparisons omitted entries that a newly available position slot could create.
- **Root cause:** the replay input contained historical fills rather than a complete chronological market stream.
- **Correction:** generate entries from fixed cadence, causal signals, historical context, and delayed cancellation state.
- **Prevention:** require a regression where the veto creates entries absent from the baseline.

### 2026-08-29 — Tested a context consumer without its HALT producer

- **Impact:** 651 historical context records became unusable because every record lacked PANIC state.
- **Root cause:** tests injected worker-owned PANIC files and did not exercise persistent HALT end to end.
- **Correction:** add a public supervisor observer with freshness and fingerprint checks.
- **Prevention:** test each required evidence source with every process that can be intentionally absent.

### 2026-08-29 — Declared historical replay before connecting selection import

- **Impact:** retained L2 archives could produce reports but could not create a version 23 selection artifact.
- **Root cause:** the first release stopped at a manual diagnostic CLI and omitted the lifecycle importer.
- **Correction:** import strict non-overlapping blocks into the existing immutable selection table.
- **Prevention:** test each evidence producer through its final authorized consumer boundary.

### 2026-08-29 — Bounded L2 storage without an archival consumer

- **Impact:** public archives grew toward the directory limit and could eventually stop capture.
- **Root cause:** the recorder documented external archival but installed no verified retention service.
- **Correction:** add daily encrypted external archival with reference-aware local rotation.
- **Prevention:** every persistent growth limit must include an installed maintenance consumer.

### 2026-08-30 — Reconciled every immutable backup during each run

- **Impact:** backup I/O grew with retained history and repeatedly triggered host reboot during deployment.
- **Root cause:** publication used a wildcard reconciliation loop instead of the current verified archive.
- **Correction:** mirror only the new archive and lower pre-update backup scheduling priority.
- **Prevention:** immutable backup work must remain proportional to newly created data.

### 2026-08-30 — Left load policy inside the hardware watchdog

- **Impact:** three responsive backup runs caused hard reboot before deployment status publication.
- **Root cause:** `max-load-1=8` treated planned I/O-wait as a host liveness failure.
- **Correction:** remove only the known default load gate and retain the device timeout.
- **Prevention:** test maintenance load independently from watchdog liveness semantics.

### 2026-08-29 — Mocked PANIC producer bypassed the transport allow-list

- **Impact:** the supervisor observer could not create PANIC state, so every HALT context row remained blocked.
- **Root cause:** unit tests injected a permissive callback and bypassed the production endpoint allow-list.
- **Correction:** permit one exact bounded public kline request and validate endpoint-specific response types.
- **Prevention:** run each new evidence source through its real transport in an integration test.

### 2026-08-30 — Reused the REANCHOR gate as dashboard strategy status

- **Impact:** persistent HALT made the general strategy gate display misleading zero evidence.
- **Root cause:** one cache identity served two evidence kinds with different meanings.
- **Correction:** calculate STRATEGY and REANCHOR gates independently and label each gate kind.
- **Prevention:** every dashboard gate must state and test its exact evidence cohort.

### 2026-08-30 — Made a monitoring audit a deployment transaction gate

- **Impact:** Pi rolled back a verified release and left the trading service stopped.
- **Root cause:** the updater treated one signed soak report run as required runtime installation work.
- **Correction:** require the timer and preserve audit failure as a trading blocker without rollback.
- **Prevention:** classify each post-install check as runtime-critical or evidence-only before enforcing rollback.

### 2026-08-30 — Tested an importer with windows the planner could not emit

- **Impact:** normal v23 planning could supply at most nine independent paths while selection required twelve.
- **Root cause:** the importer fixture used 22-hour windows and bypassed the production 18-hour planner.
- **Correction:** use four production-sized blocks, add reachability preflight, and test planner output through selection.
- **Prevention:** producer-consumer evidence tests must use the producer's real timing and capacity constants.

### 2026-08-30 — Duplicated the runtime commission authority

- **Impact:** historical context stayed blocked although the supervisor had a valid commission schedule.
- **Root cause:** the collector repeated a signed request instead of consuming the validated runtime projection.
- **Correction:** pass one timestamped, narrow fee attestation from runtime to the collector.
- **Prevention:** integration tests must reject duplicate authority reads across runtime and advisory consumers.
