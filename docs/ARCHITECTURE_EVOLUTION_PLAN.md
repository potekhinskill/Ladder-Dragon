# Architecture evolution plan

## Status and scope

Status: IN PROGRESS. Source inventories and the first read-only command pilot are implemented locally; trading workflows remain unchanged.
Review date: 2026-09-09. Source baseline: v2.20.335, commit `06c2f4f5a24cf920d4a1a03330aafb7c45d3e2c6`.
The review covers tracked source, tests, deployment files, package metadata, and current architecture controls.
It does not inspect secrets, private databases, backups, or production evidence.
This plan does not authorize deployment, cleanup, Mainnet orders, or removal of HALT.

The objective is clear ownership of behavior, not a larger number of folders.
The project remains one Python application with explicit package boundaries.
Microservices, a new framework, and a wholesale `src/` migration are outside this plan.

## Recommended order

1. Record owners, dependencies, entry points, and existing exceptions.
2. Add architecture checks in observation mode and block new violations.
3. Complete the existing dashboard and command extractions.
4. Separate accounting, public market data, and shared operational telemetry.
5. Reduce supervisor, worker, journal, and order coordinators through tested component extractions.
6. Organize prediction evidence, selection, confirmation, and model calculations.
7. Align tests, documentation, packaging, and deployment references with the completed ownership changes.
8. Enforce the complete architecture contract through the harness.

The implementing agent performs technical review before each phase within the user's authorized scope.
Review dependencies, affected contracts, behavior preservation, and acceptance checks; record the conclusion before implementation.
Ask the user before expanding scope or taking actions that require new authority.
An explicit user-requested review checkpoint still requires the user's response.
One phase can require several atomic commits; it does not require a separate Pi restart for every extraction.
Agree on the current stage and its completion checks before implementation; continue related work without requesting approval for each file.
Use the [component index](AGENT_WORKFLOW.md) for context and [project rules](../AGENTS.md) for verification and authorization.

## 1. Measured baseline

Counts use tracked files at the baseline commit. Python line counts include comments and blank lines.

| Area | Observation | Architectural consequence |
|---|---|---|
| Application | 275 Python files under `ladder_dragon/` | Package ownership needs machine-readable coverage. |
| Execution | 82 Python files | Exchange access, accounting, observers, and worker orchestration share one broad namespace. |
| Prediction | 43 Python files directly under `strategy/prediction/` | Models, stores, experiments, and promotion workflows are difficult to distinguish. |
| Commands | 72 tracked files under `bin/` | Only a selected launcher list has the 20-line gate. |
| Tests | 97 Python files directly under `tests/` | Component and cross-component responsibilities remain mixed. |
| Supervisor | `supervision/runtime.py`: 4,809 lines | `run_for_symbol` has 819 lines; `main` has 689 lines. |
| Dashboard | `dashboard/runtime.py`: 2,773 lines | Endpoint registration and substantial calculations remain together. |
| Worker | `worker/runtime.py`: 1,533 lines | Mutable process state and adapters remain coupled. |
| Worker lifecycle | `run_worker`: 512 lines | Initialization, resource ownership, and failure cleanup need explicit phases. |
| Accounting journal | `execution/order_recovery.py`: 1,279 lines | Schema, queries, and transition writers share one class module. |
| Order placement | `execution/orders/runtime.py`: 1,320 lines | Multiple order workflows still share one implementation module. |
| AI context | `ai/context/runtime.py`: 1,681 lines | Repository, attribution, calculations, and reporting share one coordinator. |
| Prediction runtime | `strategy/prediction/runtime.py`: 1,300 lines | Feature construction and durable stores remain mixed. |
| Experiment lifecycle | `experiment_lifecycle.py`: 1,483 lines | The current monolith budget register does not cover this file. |
| Episode evidence | `episode_evidence.py`: 1,321 lines | The current monolith budget register does not cover this file. |

The current directory structure is useful, but several extractions remain incomplete.
The following observations are structural findings, not proof of new trading defects.

### Existing folders do not always own behavior

- Four files under `dashboard/routers/` declare routers without endpoint handlers.
- Dashboard endpoint decorators remain in `dashboard/runtime.py`.
- `execution/orders/limit.py` and `market.py` re-export implementations from `orders/runtime.py`.
- `strategy/prediction/store.py` re-exports `PredictionShadowStore` from `prediction/runtime.py`.
- `ai/context/decision_repository.py` re-exports `AdvisorDecisionStore` from `ai/context/runtime.py`.
- Several journal modules define useful protocols, but the concrete transition writers remain in `order_recovery.py`.

A protocol is not a defect or an incomplete implementation by itself.
However, a protocol or re-export must not count as completed migration of its concrete behavior.

### Dependencies cross the documented layers

- Worker lifecycle imports startup timing from `supervision/startup_timing.py`.
- Risk Manager imports trade models and Telegram delivery from `execution/`.
- Execution imports risk asset policy and strategy prediction contracts.
- Strategy imports execution math and trade-accounting helpers.
- Persistence migration and retention entry points import domain-specific implementation modules.

These observations come from static absolute imports.
Reciprocal package dependencies do not necessarily prove an import-time module cycle.
Phase P0 must resolve relative imports, conditional imports, and runtime indirection before defining enforceable exceptions.

The architecture diagram currently labels execution as infrastructure, although execution also owns financial models and application workflows.
The final dependency policy must classify module roles, not assume every module in one broad package has identical permissions.

### Existing controls leave structural gaps

- `tests/test_architecture_layout.py` limits selected runtimes and selected test files.
- Its package-to-`bin` rule checks static imports, not every dynamic dependency mechanism.
- Some extraction tests prove file or definition presence without proving implementation ownership.
- `bin/prediction_experiment.py` has 574 lines; not every command is a thin launcher.
- The five safety audits cover important financial contracts, but they do not provide a complete architecture ownership catalog.
- Technical English validation uses a fixed document list, so new guides do not enter that check automatically.

## 2. Design rules

### Ownership before movement

Every component needs one technical owner, a public interface, allowed dependencies, and a verification contract.
The owner is a component responsibility; it is not an invented person or team.
Two modules can share a folder only when that grouping explains their common responsibility.
New folders need real consumers and cohesive behavior, not anticipated future features.

Avoid new generic containers named `common`, `utils`, `helpers`, or `misc`.
Avoid numbered successors such as `runtime2.py` that retain the original responsibility without a migration contract.
Historical strategy versions remain explicit when their identity protects immutable evidence.

### Separate four concerns

| Role | Owns | Must not own |
|---|---|---|
| Domain calculation | Exact financial meanings, policies, validated values | HTTP sessions, environment loading, service startup |
| Application workflow | Ordering, resource lifetime, transaction coordination | Duplicate financial formulas or provider parsers |
| Adapter or repository | Exchange access, SQLite storage, filesystem operations | Independent promotion or risk authority |
| Entry point | Argument parsing handoff, application construction, process exit | Reusable trading or reporting logic |

Domain policy consumes validated values and narrow interfaces.
The application constructs adapters and injects them into workflows.
The plan does not require a universal `domain/application/infrastructure` folder hierarchy for every component.

### Preserve capability boundaries

- Public market collection receives no account credentials or order mutation capability.
- Dashboard exchange access stays read-only.
- The existing reviewed AI control endpoint retains its authentication, schema checks, and advisory-only scope.
- AI calculations receive no order tools or complete execution runtime object.
- Risk decisions do not send Telegram messages directly after extraction; an injected notification adapter handles delivery.
- Signed account, open orders, and reconciliation retain their reviewed sequential order.
- Authority checks retain their actual call frequency, identity verification, and position before protected operations.

## 3. Target source layout

The tree describes intended owners, not directories to create immediately.
Existing public commands, ASGI launch paths, service names, configuration names, and durable data paths remain stable.

```text
ladder_dragon/
  accounting/               exact trade models, FIFO, commissions, inventory, reports
  market_data/              public observations, public transport, market collection
  observability/            bounded timing, sanitized events, notification adapters
  execution/
    venue/                  signed Binance adapter and provider response contracts
    orders/                 actual LIMIT, MARKET, OCO, and OTOCO workflows
    protection/             residual protection and emergency-exit workflows
    journal/                concrete intent repositories and atomic transitions
    worker/                 worker composition, phases, event loop, explicit state
  supervision/
    startup/                startup checks, retry orchestration, cleanup
    planning/               per-symbol plan construction and admission
    snapshots/              risk snapshot, valuation, protection observations
    runtime.py              small composition and scheduling coordinator
  strategy/
    prediction/
      modeling/             features, models, inference, ensemble
      evidence/             stores, episode observations, immutable source contracts
      selection/            historical datasets, replay planning, candidate selection
      confirmation/         frozen experiments, statistical evaluation, versioned contracts
      promotion/            registry, activation records, admission projections
  risk/                     risk policy, state repository, narrow input contracts
  ai/                       advisory policies and real-evidence attribution
  dashboard/
    routers/                actual authenticated endpoint handlers
    services/               read models and endpoint use cases
    repositories/           read-only data access
    app_factory.py          application assembly and dependency wiring
  persistence/              SQLite safety, connection policy, migration infrastructure
  market_analysis/          scenario calculations and analysis workflow
  verification/
    architecture/           planned architecture policy loader and analyzers
    checks/                 required harness check adapters
    live/                   explicitly authorized verification workflows
  deployment/               application-facing deployment status
bin/                        stable executable launchers
deploy/                     installation, service definitions, host administration
FRONT/                      existing dashboard assets and vendor inventory
tests/                      component tests, shared fixtures, cross-component contracts
docs/                       current guides and this proposed migration plan
```

Public collection currently inside `market_analysis/` can move only after its public-only capability contract is preserved.
Market calculations must not acquire network access merely because they move near a public adapter.
`execution/venue/` keeps provider-specific validation; `accounting/` receives validated financial records.
Provider payload schemas must not become the accounting model.

The `prediction/promotion/` package owns records and policy evidence, not exchange execution authority.
Supervisor and worker still enforce admission at their mutation-capable boundaries.

## 4. Concrete migration map

Every row requires caller migration, focused tests, source-contract updates, and removal of obsolete implementation ownership.
Destination filenames are proposals; final names follow the verified component responsibility.

| Current source | Proposed owner or extraction | Main acceptance condition |
|---|---|---|
| `execution/trade_accounting.py` | `accounting/models.py`, `accounting/commissions.py`, `accounting/fifo.py` | Exact results and commission provenance remain identical. |
| `execution/tools_stats.py` | `accounting/repositories/`, `accounting/inventory.py` | Trade persistence, retries, and inventory results retain their contracts. |
| `execution/inventory_lots.py` | `accounting/lots.py` | Lot identity and restart idempotency remain unchanged. |
| `execution/executor_stats.py` | `accounting/imports.py` with an injected fill reader | A failed required callback cannot advance the cursor. |
| Cost-basis import and retirement modules | `accounting/maintenance/` | Existing operator approvals and evidence preservation remain mandatory. |
| `execution/binance_transport.py`, `exchange_evidence.py` | `execution/venue/transport.py`, `evidence.py` | Reviewed callers retain exact capability and validation contracts. |
| Public parts of `tools_market.py`, `executor_market.py` | `market_data/` | Separate public reads from signed account reads before moving code. |
| `market_tickers.py`, `market_http_body.py` | `market_data/tickers.py`, `http_body.py` | Bounds, exact prices, and current-snapshot ownership remain intact. |
| Market and user stream modules | Public observer under `market_data/`; private observer under `execution/` | Public and signed session lifetimes remain separate. |
| `supervision/startup_timing.py`, execution timing helpers | `observability/` | Worker no longer imports supervision for shared timing. |
| `execution/telegram_alerts.py` | `observability/notifications.py` | Domain code uses an injected sink without credentials. |
| Supervisor startup functions | `supervision/startup/` | Every failure path records elapsed time and releases owned resources. |
| `run_for_symbol` and plan helpers | `supervision/planning/` | Per-symbol authority and admission order remain executable contracts. |
| `risk_cycle.py`, valuation and protection snapshots | `supervision/snapshots/` | Freshness, route selection, signed ordering, and snapshot agreement remain unchanged. |
| `execution/order_recovery.py` | Concrete implementations inside `execution/journal/` | Lifecycle writers preserve atomicity and complete residual-quantity evidence. |
| `orders/runtime.py` | Real implementations in existing order modules | No accepted response bypasses intent validation or durable uncertainty. |
| `worker/runtime.py`, `worker/lifecycle.py` | Explicit state, dependencies, startup phases, shutdown coordinator | Signal changes and replaced connections remain visible after initialization. |
| `dashboard/runtime.py` | Existing routers, services, repositories, application factory | Route methods, authentication, response schemas, and read-only behavior remain identical. |
| `prediction/runtime.py`, `store.py` | Actual evidence repository and separate modeling functions | No store module imports the former runtime implementation. |
| `experiment_lifecycle.py`, `episode_evidence.py` | Confirmation workflow, evidence repository, statistical calculations | Frozen identifiers, cutoffs, append order, and transaction boundaries remain exact. |
| `historical_*`, `v23_*`, model modules | Selection, confirmation, and modeling owners | Historical evidence never gains current execution authority. |
| `ai/context/runtime.py`, repository re-export | Concrete decision repository, attribution, feature and reporting services | Only verified real evidence reaches readiness and retrieval. |
| Large `bin/` reports and experiment commands | Package-owned reporting or experiment entry modules | Existing command names, options, exit codes, and operator guards remain stable. |
| `bin/audit_*.py` implementations | Package-owned verification analyzers | Existing audit commands and failure semantics remain stable. |

Do not move complete mixed modules merely to satisfy this table.
First separate their responsibilities behind tested interfaces; then move each responsibility to its owner.
Update canonical-owner references in `docs/DOMAIN_AUTHORITIES.md` and existing safety audits in the same implementation change.

## 5. Implementation phases

| Phase | Work | Depends on | Exit evidence |
|---|---|---|---|
| P0: inventory | Record every source owner, command, import edge, guarded writer, store, asset, and current exception. | Approved plan | Reproducible baseline tied to an exact commit. |
| P1: initial controls | Add the architecture catalog and analyzers; reject new violations without hiding existing debt. | P0 | Mutation tests prove each rule detects its intended violation. |
| P2: presentation and commands | Complete actual dashboard extraction; move reporting and audit logic out of launcher files. | P1 | Route and CLI parity; source inspection confirms new implementation owners. |
| P3: shared ownership | Extract accounting, public market reads, and timing; remove the corresponding cross-layer dependencies. | P1 | Exact financial parity, public capability isolation, smaller import graph. |
| P4: execution workflows | Decompose journal writers, order workflows, worker resources, and supervisor phases. | P3 | Restart, partial-fill, protection, cancellation uncertainty, and cursor-retry regressions pass. |
| P5: prediction and AI | Separate modeling, evidence, selection, confirmation, promotion records, and advisory attribution. | P3; P4 for moved authority paths | Identical evidence interpretation and no new runtime capability. |
| P6: repository consistency | Align tests, documentation, assets, migrations, command references, and packaging. | Each affected phase | Installed-package smoke tests and path-contract tests pass. |
| P7: permanent enforcement | Remove migrated exceptions and make the full architecture contract mandatory. | P2 through P6 | Local, release, and CI runs reject all injected structural regressions. |

P6 checks accompany every move; P6 also provides a final repository-wide audit.
P7 must not become an excuse to leave completed extractions unenforced.
Each extraction enables its blocking rule in the same change.

### First implementation slice

The first slice is P0 and the smallest useful part of P1.
It adds the ownership catalog, reports current exceptions, and prohibits unknown new source locations.
It does not move trading code or restart Pi.
The first behavior extraction should complete one dashboard route group or one read-only reporting command.
This tests the migration procedure before changing accounting or execution orchestration.
The reviewed local pilot is `stats_view`; its scoped ownership, CLI, and read-only contracts accompany its extraction.
This pilot does not declare the broader P0 or P1 phases complete.
The second local pilot moves `audit_backtest_reports` into the verification package with unchanged implementation syntax and executable output contracts.
The next pilot moves the numeric audit and its policy bindings into the verification package without changing budgets.
Its tests verify checkout resolution and rejection through the actual local and release harness command.

### Change boundaries

- Separate mechanical moves from intentional financial or performance changes.
- Do not combine FIFO optimization with accounting relocation.
- Do not change SQL schema, stored values, experiment identifiers, or execution fingerprints as a side effect of a move.
- If a move changes a source-bound fingerprint, stop and classify the compatibility impact before release.
- Keep migration resource paths and checksums unchanged initially.
- If migration resources must move, verify installed package data and all historical migration paths in that separate change.
- Do not rewrite historical evidence to match a new module name.
- Keep executable compatibility entry points; do not create import-only legacy aliases for old tests.
- Preserve mutable signal and resource state through explicit state objects, not copied configuration snapshots.

## 6. Permanent harness rules

After implementation, the new architecture rules must become required harness checks.
Each completed phase must update its rules immediately; the final phase makes the complete contract mandatory.
Documentation alone does not complete this requirement.

### Planned enforcement files

The listed paths now implement Python ownership and the static package-to-launcher boundary only.
Their broader target responsibilities remain proposed.

| Proposed path | Responsibility |
|---|---|
| `schemas/architecture_contract.json` | Versioned component owners, allowed imports, public interfaces, budgets, entry points, and exceptions |
| `ladder_dragon/verification/architecture/` | Contract validation, source inventory, import resolution, graph analysis, and ownership checks |
| `ladder_dragon/verification/checks/architecture.py` | Required check integration with the existing harness result model |
| `bin/audit_architecture.py` | Stable thin launcher for the package-owned analyzer |
| `tests/architecture/` | Positive cases, negative mutations, migration-contract tests, and report-schema tests |

The architecture contract must reference existing safety authorities rather than create a competing list of financial owners.
The analyzer must not import production modules to discover their dependencies.
Source inspection must not load `.env`, read private state, contact Binance, or initialize application resources.

### Rule catalog

| Rule | Required behavior | Negative test |
|---|---|---|
| A01: complete ownership | Assign every tracked production source to exactly one most-specific owner. Reject unknown paths and conflicting owners. | Add a source file outside registered components. |
| A02: directed dependencies | Resolve absolute and relative imports against module-role rules. Prohibit package imports from executable launchers. | Hide a forbidden import behind an alias, relative path, or nested scope. |
| A03: cycle control | Detect strongly connected module groups. Reject new cycles and growth of reviewed legacy cycles. | Introduce a two-module cycle inside one package. |
| A04: capability isolation | Keep public collection, dashboard reads, and advisory policies outside mutation-capable dependency paths. | Add an indirect dependency on the signed mutation adapter. |
| A05: real ownership | Require migrated definitions at their canonical owner. Reject reverse delegation to the former monolith. | Replace an extracted implementation with a same-name re-export or forwarding wrapper. |
| A06: size and complexity | Apply budgets to every new module and function; ratchet existing exceptions downward after extraction. | Add a new oversized module not present in the old monolith list. |
| A07: entry points | Discover every `bin` command and the ASGI launcher. Enforce thin entry points after their recorded migration. | Add business logic to a previously migrated launcher. |
| A08: state and dependency scope | Prohibit new whole-runtime mappings or namespace mutation outside registered transitional adapters. | Pass `globals()` into a new domain service. |
| A09: canonical financial meaning | Retain all five safety audits, exact closure contracts, guard provenance, and runtime identity checks. | Move a protected call after a mutation or replace its binding. |
| A10: durable ownership | Register store writers, transaction boundaries, migration resources, and retention classification. | Add an unregistered writer or omit packaged migration data. |
| A11: interface and deployment parity | Verify commands, route sets, service paths, frontend assets, and installed package resources. | Move a file while leaving a source-contract or deployment reference stale. |
| A12: documentation and test ownership | Check all current guides, navigation links, component tests, and cross-component contracts. | Add an unindexed guide or leave tests importing a removed owner. |

Static checks cannot prove every runtime property.
Dynamic import expressions require explicit review; literal targets enter the graph, and unresolved targets require a bounded exception.
Capability rules need runtime spies and denial tests in addition to import analysis.
Financial-writer rules need real temporary SQLite transactions, not only a search for SQL strings.

### Initial proposed limits

- New production modules: at most 500 physical lines.
- New functions: review above 80 physical lines; reject above 120 without an approved exception.
- New focused test modules: at most 600 physical lines, excluding separately owned generated fixtures.
- Migrated CLI launchers: at most 20 physical lines, preserving the existing project convention.
- Package initializers: declarations and intentional public exports only; no resource initialization or compatibility identity replacement.
- Existing oversized modules: exact measured baselines, never an automatic increase to pass a test.

These numbers are proposed starting limits, not implemented policy or proof of architectural quality.
P0 must measure their effect before approval.
Do not compress statements, remove useful comments, or scatter cohesive behavior across tiny files to satisfy a line limit.
Also report dependency fan-out, function size, and public-interface growth for review.
Do not impose a universal file-count limit on every package.

### Size-limit impact review — 2026-09-10

This P0 measurement precedes A06 enforcement; it does not approve exceptions or change existing harness limits.
It covers 373 production Python files, 239 test files, and 2,139 production function definitions in the working candidate.
Production means inventoried Python source outside `tests/`; commands and deployment Python are included.
The inventory includes tracked and nonignored new files, excluding ignored environments and private state.
Comparison source: `06c2f4f5a24cf920d4a1a03330aafb7c45d3e2c6`; the working tree is not an immutable release.
Sorted source identity: `9cc43cc92d6b13d910a28ef66086036144b3ed77eb0da1c6898f82987f9218a5`.
The digest hashes each relative UTF-8 path, a zero byte, and its binary SHA-256 content digest, in sorted path order.
Module size counts physical lines, including blanks and comments.
Function size spans its first decorator or definition through its AST end line, including nested definitions.
Async functions and methods are included; lambdas are excluded.

| Proposed boundary | Current observations | Interpretation |
|---|---|---|
| Production module above 500 lines | 43 files | Existing debt needs exact-path review; a universal immediate limit would reject it. |
| Production function above 80 lines | 197 definitions | Review threshold, not an automatic rejection threshold. |
| Production function above 120 lines | 104 definitions | Existing function debt needs qualified identities and immutable baselines. |
| Test module above 600 lines | 18 files | Broad test modules need ownership review, not automatic splitting. |
| Newly added production modules | 17 files; maximum 168 lines | All satisfy the proposed module limit. |
| Functions in newly added production modules | None above 80 lines | All satisfy both proposed function thresholds. |
| Newly added test files | None above 600 lines | No new test-file exception is needed for this candidate. |
| New functions in modified existing production files | None | The check must still cover this path in future candidates. |

New means absent from the comparison commit, not absent from the current Git index.
For modified files, function comparison uses lexical class and function names; duplicate qualified definitions block this measurement.
Five existing functions grow in the candidate:

| Source | Qualified function | Baseline lines | Candidate lines |
|---|---|---:|---:|
| `bin/daily_trading_digest.py` | `build_digest` | 50 | 59 |
| `ladder_dragon/ai/ai_advisor.py` | `AIAdvisor.recommend` | 121 | 129 |
| `ladder_dragon/ai/ai_advisor.py` | `AIAdvisor._log_usage` | 55 | 59 |
| `ladder_dragon/supervision/runtime.py` | `run_for_symbol` | 819 | 824 |
| `ladder_dragon/verification/checks/unit.py` | `local_checks` | 54 | 60 |

Two growth cases already exceed 120 lines; the proposed ratchet cannot silently accept their larger candidate sizes.
These changes predate this measurement and are preserved; this review does not establish a new functional defect.
Existing module budgets do not enforce a complete function-size ratchet.
The largest functions are `run_for_symbol` at 824 lines, supervisor `main` at 689, and `build_risk_snapshot` at 672.
Next implementation: report qualified function spans in the bounded architecture inventory, with decorator, async, nested-definition, and duplicate-identity tests.
Then enforce approved new-code limits and review exact legacy growth separately against verified release lineage.
Do not introduce candidate-generated allowances, compress statements, or split financial workflows merely to satisfy physical line limits.
This review leaves A06 enforcement pending; complete per-function exception records and ownership review remain necessary.
The next measurement slice records each function's lexical name, physical span, async status, and duplicate-name ambiguity in the existing bounded inventory.
Review found legitimate overload definitions; the inventory preserves all duplicates rather than rejecting valid source or silently choosing one definition.
Future budget comparison must resolve or block ambiguous identities before it grants an allowance; observation alone does not authorize growth.
Decorator lines now contribute to the reported maximum; nested bodies remain included in their containing function's span.
No new persistent store, size limit, exception, trading behavior, or release permission is introduced.
The implemented measurement passes 29 focused tests and the full suite: 2,531 passed, one skipped; compileall and five safety audits pass.
The observed inventory contains 2,140 function definitions across 374 source files and remains below the unchanged 2 MiB report ceiling.
Three overloaded `WalkForwardTrainingPrefix.__getitem__` definitions remain separate and explicitly ambiguous; A06 budget enforcement remains pending.
The operator approved new-code limits on 2026-09-10: 500 module lines, 120 function lines, and a review warning above 80 function lines.
The reviewed implementation scope is new production paths and new lexical names, including definitions added inside existing files.
The required `architecture_new_sizes` check selects its predecessor through canonical release continuity; unavailable history blocks classification.
Renamed or moved definitions are new identities; removed definitions cannot retain an allowance through candidate-controlled baselines.
Unchanged ambiguous name groups remain legacy only when their span multisets match; changed groups block classification rather than receiving allowances.
This does not prove runtime identity or enforce legacy growth; existing oversized functions and the proposed test-file limit require separate work.
No exception mechanism or candidate-controlled threshold is added; existing comprehensive checks remain required.
The new-code check passes 35 focused tests and the full suite: 2,548 passed, one skipped; compileall and five safety audits pass.
Diagnostic comparison with source baseline `06c2f4f5a24cf920d4a1a03330aafb7c45d3e2c6` finds no new-code size violations, warnings, or changed ambiguous groups.
This diagnostic result is not a release PASS; legacy-growth enforcement and exact exception review remain pending.
The next reviewed slice adds required legacy-growth enforcement against the same verified predecessor, without candidate-generated exceptions.
Review conclusion: existing code can remain within the greater of its historical size and the standard limit, but cannot increase that ceiling.
The `architecture_legacy_sizes` check covers existing production paths and function names; ambiguous changed groups block comparison.
Historical module sizes include comments and blank lines; missing physical-size metadata blocks analysis instead of substituting AST statement spans.
Unchanged debt remains subject to component-owner review during extraction; this non-growth rule does not approve its design or waive financial controls.
The full exact-path exception catalog and test-file limits remain pending.
Diagnostic comparison against source baseline `06c2f4f5a24cf920d4a1a03330aafb7c45d3e2c6` rejects four existing-size increases in this candidate.

| Source or definition | Historical lines | Candidate lines |
|---|---:|---:|
| `ladder_dragon/ai/ai_advisor.py` | 825 | 835 |
| `AIAdvisor.recommend` in that module | 121 | 129 |
| `ladder_dragon/supervision/runtime.py` | 4809 | 4814 |
| `run_for_symbol` in that module | 819 | 824 |

These earlier candidate changes remain intact; the check does not create an exception or a release PASS.
Next: extract the added advisory diagnostics and expectancy-status publication behind tested interfaces while preserving fallback, gates, and safe logging.
Do not remove useful diagnostics or compress statements merely to satisfy the measured ceilings.
Legacy-size enforcement passes 45 focused tests and the full suite: 2,558 passed, one skipped; compileall and five safety audits pass.
Both actual profiles reject threshold crossings and block missing lineage; the four diagnostic candidate violations remain unresolved.
The correction extracts advisory failure publication into `ai/advisor_diagnostics.py` and expectancy serialization into `supervision/expectancy_status.py`.
Review preserves existing log callbacks, their order, negative-cache ownership, exact decimal strings, and APPLY-only status semantics.
The status builder owns no runtime mapping or exchange capability; the failure publisher receives current callbacks rather than the complete advisor object.
Module budgets decrease to 822 advisor lines and 4803 supervisor lines; source-layout checks enforce these ceilings immediately.
No financial calculation, threshold, schema, execution gate, or deployment behavior changes.
The completed extraction passes 44 focused tests and the full suite: 2,560 passed, one skipped; compileall and five safety audits pass.
`AIAdvisor.recommend` now has 116 lines and `run_for_symbol` has 812; all four earlier size violations are absent.
Diagnostic new-size, legacy-growth, and cycle comparisons against the source baseline pass without exceptions; this is not a release PASS.
Next component review: complete one existing dashboard route group or remaining reporting command, with interface parity and ownership enforcement in one change set.
The next P2 component is the complete monthly prediction reporting command, including evidence loading, output serialization, and notification-state handling.
Review preserves the original implementation syntax, command parser, cutoff behavior, state replacement, and optional notification policy.
The concrete owner is `strategy/prediction/monthly_report_command.py`; `bin/monthly_prediction_report.py` remains the executable entry point.
No service arguments, timer, schema, retention, trading authority, or prediction calculation changes.
Tests use isolated synthetic evidence and intercepted notifications; no production report or external message is created during verification.
The monthly command component passes 116 focused tests and the full suite: 2,568 passed, one skipped; compileall and five safety audits pass.
Package discovery and diagnostic ownership, size, and cycle comparisons pass; no additional cyclic edges or size exceptions are introduced.
The command is a completed local P2 component; remaining reporting commands and dashboard extraction stay open.

### Exception policy

Each exception needs a rule identifier, exact path, technical owner, rationale, baseline, removal condition, and target review milestone.
Wildcards that exempt all future files are forbidden.
An exception cannot disable a financial safety check.
Deleted or migrated files automatically lose their exceptions.
The analyzer compares budgets with the reviewed base commit; a candidate cannot silently approve its own higher limit.
Missing base history blocks the comparison instead of returning PASS.
Any approved limit increase requires a separate review record and its own tested rationale.

### Harness integration and reporting

The required `architecture_ownership` check now runs through `verification/checks/unit.py` in local and release profiles.
Additional architecture rules must use this same required-check integration.
CI already runs the local profile for Python 3.10, 3.11, and 3.12; it must exercise the new checks there.
Pi verification consumes the exact PASS release artifact; it must not bypass source checks because the Pi is already running.

Use `FAILED` for a proved violation and `BLOCKED` when required inputs or analysis are unavailable.
A skipped, crashed, or incomplete analyzer cannot count as PASS.
Mutation tests must verify check invocation through the real profile, not just call the analyzer directly.

The report contains commit SHA, contract hash, source counts, dependency edges, violations, and remaining exceptions.
Use repository-relative paths and fixed diagnostic labels only.
Do not include source payloads, private absolute paths, credentials, balances, or runtime evidence.

Architecture reports are derived release evidence, not authoritative trading state.
Keep one bounded report per verified commit under the existing verification artifact workflow.
Proposed maximum report size: 2 MiB; overflow returns BLOCKED with aggregate counts.
Published release manifests retain their existing release retention policy.
Local intermediate reports are disposable only through approved, exact-path cleanup.
No new Pi database, archive job, or recurring service is required.

## 7. Tests, documentation, and deployment layout

### Tests

Component tests should mirror component ownership, not copy every production directory mechanically.
Use `tests/accounting/`, `tests/market_data/`, and `tests/architecture/` only when their corresponding components exist.
Keep shared synthetic provider responses and database fixtures in `tests/support/`.
Keep end-to-end safety contracts separate from pure unit tests.
Test modules must not become production dependencies.

Every financial extraction needs positive, fail-closed, and retry or restart cases.
Preserve the regression scenarios for partial exits, foreign identities, incomplete commissions, and failed lot synchronization.
Tests must prove that unknown read results cannot authorize cancellation or new exposure.

### Documentation

Keep `docs/ARCHITECTURE.md` as the architecture entry page.
Update its current-state description only after an extraction is verified.
Keep this plan visibly proposed until each phase has completion evidence.
Link architecture, domain authorities, command reference, configuration, retention, and release procedures without duplicating their policies.

Add automatic discovery or a checked manifest for every current Markdown guide in the harness.
Preserve historical decisions and mistake records; this plan does not authorize truncation or archival of those files.
The reviewed [learning index](AGENT_WORKFLOW.md#task-routing-and-learning-index) now routes required reading by affected boundary.
Historical records remain intact; current project rules supersede historical workflow instructions.

### Deployment and frontend

Keep `FRONT/` and `FastAPI/pi-dashboard/app.py` stable during the initial migration.
Renaming them for style alone has low value and affects deployment references and asset verification.
Keep vendor files and licenses under their existing verified ownership.

Do not reorganize `deploy/` until script references, service templates, command documentation, and asset checks have a complete manifest.
A later grouping of service templates is optional, not a prerequisite for application decomposition.
The stable updater command remains `deploy/update_raspberry_pi.sh update <40-char-SHA>`.

Do not move runtime databases, HALT, risk state, `.runtime/`, logs, environment files, or archives during source cleanup.
Encrypted backups remain on the external disk, not the Pi flash filesystem.
Deployment must preserve configured service state and current execution mode.

Every source move must review `deploy/depth_restart_policy.py` before deployment.
Unknown changed paths currently require a depth restart; new package names can therefore affect evidence continuity.
Do not expand the preserve list merely to avoid a restart.
Prove runtime dependency isolation first, then update the policy and its rename tests if justified.

## 8. Change-set acceptance checklist

Apply this checklist to the agreed change set, not after each intermediate file edit.
Use affected tests during iteration; complete every applicable check before declaring the change set complete.

- [ ] Record the exact source and destination owners before editing.
- [ ] Search imports, dynamic loaders, string paths, systemd references, tests, audits, schemas, and package-data declarations.
- [ ] Preserve public interfaces and separate intentional behavior changes from movement.
- [ ] Move the implementation and all internal callers together.
- [ ] Update existing canonical authority and mutation-path checks without weakening their conditions.
- [ ] Prove resource cleanup and mutable-state visibility after restart or signal changes.
- [ ] Preserve Decimal values, FIFO allocation, fees, order identities, cursor progress, and transaction boundaries.
- [ ] Preserve all historical identifiers, evidence hashes, cutoffs, and migration checksums.
- [ ] Lower migrated monolith budgets and remove completed exceptions.
- [ ] Run architecture mutation tests, affected component tests, all five safety audits, and the full suite.
- [ ] Run compileall, Technical English, package smoke checks, and documentation contracts.
- [ ] For implementation releases, update the dated changelog and version according to repository rules.
- [ ] Require release continuity, signed artifacts, and successful CI before authorized deployment.
- [ ] After authorized deployment, verify exact SHA, assets, services, heartbeat, reconciliation, API protection, and preserved HALT.

Current verification commands remain:

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m compileall -q .
PYTHON_DOTENV_DISABLED=1 PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m bin.check_technical_english
```

The command `.venv/bin/python -m bin.audit_architecture` now implements the first ownership slice.
Its PASS result does not prove completion of the remaining architecture rules.

## 9. Completion and rollback

The program is complete when implementation ownership matches the catalog and required harness checks prevent new structural drift.
Completion also requires migrated callers, no expired exceptions, stable installed entry points, and unchanged financial regression results.
Empty routers, new re-export files, and renamed monoliths do not satisfy completion.

No startup speed improvement is assumed from folder changes.
Measure import, startup, snapshot, and accounting costs separately before and after relevant extractions.
Use comparable workloads and several natural Pi starts; do not restart evidence collection just to collect timing samples.

Stop an extraction when financial outputs, safety order, evidence identity, or resource lifetime changes unexpectedly.
Before publication, correct the local candidate without rewriting a published release.
After publication, use the reviewed deployment recovery procedure or a new signed corrective release.
Do not hand-edit production databases or restore old schemas to make a source rollback appear compatible.

## 10. Implementation record

The first local slice covers exact Python owners, static import observations, size metrics, and the package-to-launcher prohibition.
It includes nonignored new source files so local additions cannot silently escape the inventory.
Its report uses source hashes alongside HEAD and does not claim a dirty checkout is an immutable release.
P0 still needs the complete store, writer, asset, command-contract, dynamic dependency, and exception inventory.
The [state and policy map](ARCHITECTURE_STATE_MAP.md) now records 18 store families and seven canonical policy sources.
The required `architecture_references` check detects stale anchors in local and release profiles.
These references do not prove complete writer coverage or authorize new mutations.
The [command and deployment source map](ARCHITECTURE_SURFACE_MAP.md) registers 146 command, deployment, frontend, and migration files.
The required `architecture_surfaces` check verifies exact membership and command guide coverage in local and release profiles.
Command behavior, deployment reference edges, installed destinations, and package parity still need complete contracts.
The service-link check now records 25 unit templates, 27 direct edges, and seven literal installed-file mappings.
It requires reviewed directive fingerprints and existing targets without proving shell reachability or installed state.
The Python inventory now reports CLI declaration locations and syntax fingerprints without evaluating defaults or importing command modules.
The verified local inventory observes 827 syntactic CLI sites across 67 modules.
These observations do not resolve parser identity, command reachability, dynamic declarations, or executable CLI parity.
P1 still needs the remaining graph, capability, ownership-migration, and budget rules.
Dynamic dependency observations now cover `importlib.import_module`, `__import__`, and explicit import aliases without executing source.
Literal relative targets require a literal package; unknown expressions remain explicit observations without disclosed arguments.
The local inventory observes zero matching calls across 369 production Python files; this does not exclude other dynamic loading forms.
Assignment aliases, rebinding, file-based loaders, runtime reachability, and complete dependency graphs remain unresolved.
Synthetic local and release profile tests exercise nested calls, literal targets, uncertain arguments, and source-only inspection.
This slice passes 40 focused tests and the full suite: 2,463 passed, one skipped.
Compileall, five safety audits, package discovery, and Technical English pass; installed-package and complete graph verification remain separate.
No full phase is marked complete by this slice.
Static dependency observations now resolve candidate imports to real source paths and package initializers.
The local graph contains 370 source nodes, 1,403 edges, and three cyclic groups of 2, 17, and 15 files.
These groups include conditional imports and package initialization; they do not prove runtime failures or define approved legacy exceptions.
Ambiguous module identities block both harness profiles; cycle budgets and complete dynamic dependency resolution remain pending.
The static graph slice passes 51 focused tests and the full suite: 2,474 passed, one skipped.
Cycle detection matches independent reachability on every three-node graph and handles long chains without recursive traversal.
Fill this record only after the corresponding implementation and verification complete.
Cycle diagnostics now distinguish explicit candidate imports from dependencies introduced by parent package initialization.
The market-analysis and verification groups have no direct-only cycles; prediction retains one direct-only group of 12 files.
Combined graph membership remains unchanged; these observations do not prove runtime failure or approve cycle-budget exceptions.
The cycle-kind slice passes 54 focused tests and the full suite: 2,477 passed, one skipped.
Prediction includes deferred and type-checking imports; their execution context still needs explicit classification before startup-cycle claims.
Loader searches found no additional supported call forms in production source; file loaders, assignment aliases, and generated code remain outside complete proof.
Import context observations now identify deferred functions, conditional blocks, class bodies, and candidate positive type-guard branches.
The current inventory contains 372 source files, 1,410 edges, and 785 local import sites; its unguarded direct view has no cycles.
This view is not a startup proof; guard rebinding, conditional execution, and runtime reachability remain unverified.
The complete graph retains all contexts; syntax flags cannot grant capability or remove cycle-policy obligations.
The context slice passes 66 focused tests and the full suite: 2,503 passed, one skipped.
Compileall, five safety audits, package discovery, and Technical English pass; cycle budgets and runtime capability verification remain pending.
The required `architecture_cycles` check now enforces A03 for direct static cyclic edges against `release_continuity.previous_sha`.
New groups, group merges, internal edge additions, and restored cyclic edges fail; missing verified history blocks analysis.
Historical source is read from bounded Git objects with replacement objects disabled, never from the candidate's working files.
Initializer-only cycles and dynamic dependencies remain outside this initial blocking rule.
Existing direct prediction debt belongs to `strategy.prediction`, with P5 as its review milestone and removal of cyclic edges as its exit condition.
Its rationale is compatibility during staged evidence and runtime decomposition; exact paths and edges come from the verified previous-release source graph.
This allowance cannot exceed that graph or bypass financial audits; each release uses its predecessor, so removed edges lose their allowance.
The direct cycle-growth slice passes 28 focused tests and the full suite: 2,517 passed, one skipped.
Compileall and five safety audits pass; synthetic local and release profiles prove both acceptance and rejection.
The current working candidate remains BLOCKED for cycle analysis because verified release lineage is unavailable; this is not a release PASS.
The next reviewed slice extends A03 to initializer-inclusive cyclic edges while retaining independent direct-cycle enforcement.
Review conclusion: conservative source restrictions can prevent dependency growth without interpreting initializer cycles as runtime failures.
Both comparisons use the same verified predecessor; combined debt never grants a direct-cycle allowance.
Existing initializer-inclusive debt follows its registered component owner, with review during that component's extraction and removal of cyclic edges as its exit condition.
Its rationale is staged compatibility; the exact predecessor graph limits every allowance, including conditional and deferred source imports.
Dynamic dependencies and runtime capability proofs remain outside this slice.
Diagnostic comparison with source baseline `06c2f4f5a24cf920d4a1a03330aafb7c45d3e2c6` finds 20 additional combined cyclic edges and no additional direct cyclic edges.
The verification initializer imports `HarnessRunner`, connecting the profile checks back to their package initializer.
This comparison is not a release PASS or an approved exception; the existing candidate violates the expanded source restriction.
Next: review the initializer's exported interface and remove its coordinator dependency, with caller migration and executable import parity checks.
Initializer-inclusive enforcement passes 32 focused tests and the full suite: 2,521 passed, one skipped.
Compileall, five safety audits, and documentation checks pass; the detected candidate dependency growth remains unresolved.
The initializer correction removes the unused package-level `HarnessRunner` export, preserving result-model identity and canonical runner imports.
Review found no repository consumer of the removed export; external callers using it must select `ladder_dragon.verification.runner` instead.
No runner implementation, executable command, financial behavior, or deployment interface changes.
After correction, the diagnostic comparison with the same source baseline passes: combined cyclic edges decrease from 98 to 60, below baseline 78.
All 20 additional edges are absent; direct cyclic edges remain 32, with no new edges in either comparison.
This closes the detected initializer regression without an exception; release verification and broader architecture phases remain separate.
The correction passes 39 focused tests and the full suite: 2,523 passed, one skipped.
Compileall and five safety audits pass; fresh-process import tests preserve result identity and canonical runner availability.

| Phase | Status | Reviewed commit | Verification artifact | Remaining exceptions |
|---|---|---|---|---|
| P0 | In progress: Python, store anchors, source surfaces | Local candidate | Scoped command output | Complete writers and reference edges pending |
| P1 | In progress: scoped ownership, references, and surfaces | Local candidate | Required harness checks and mutation tests | Graph, capability, and parity rules pending |
| P2 | Local components: statistics viewer, saved-report audit, numeric audit, monthly report | Local candidate | Syntax parity, executable CLI tests, harness rejection | Other commands and dashboard pending |
| P3 | Pending | Not implemented | None | Not inventoried |
| P4 | Pending | Not implemented | None | Not inventoried |
| P5 | Pending | Not implemented | None | Not inventoried |
| P6 | Pending | Not implemented | None | Not inventoried |
| P7 | Pending | Not implemented | None | Not inventoried |

Related current contracts: [Architecture](ARCHITECTURE.md), [Domain authorities](DOMAIN_AUTHORITIES.md), and [Local artifacts](LOCAL_ARTIFACTS.md).
