# Architecture evolution plan

## Status and scope

Status: IN PROGRESS. Source inventories, scoped enforcement, registered command ownership, and initial dashboard route extraction are implemented locally.
Architecture moves preserve behavior; separate functional fixes in the working candidate remain outside this plan's progress count.
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

### Twenty-fourth five-step P2 slice — 2026-09-26

Review conclusion: separate advisory-control presentation without changing authentication, request-forgery protection, configured modes, or canonical file writes.
The five steps cover two HTTP operations and three ownership and integration boundaries; this slice does not claim five new routes.

| Step | Boundary | Completed implementation |
|---|---|---|
| 1 | Control snapshot | `dashboard/control_snapshot.py` owns configured-mode, enablement, and read-error presentation |
| 2 | `GET /api/ai/control` | Concrete handler in `dashboard/routers/control.py`; preserve payload and unavailable HTTP 503 |
| 3 | `POST /api/ai/control` | Concrete async handler preserves configuration rejection, Boolean validation, canonical writer, and response |
| 4 | Live dependencies | Five declared bindings preserve current paths, runtime configuration, readers, and writer |
| 5 | Application integration | Register the router once and require explicit method, async, snapshot-owner, and live-binding contracts |

The application retains authentication, rate limits, request-forgery protection, and the token endpoint.
Canonical `ai/ai_control.py` remains the file-format and atomic-write owner; the dashboard introduces no alternative writer or execution permission.
The submitted mode cannot replace the configured mode; an unconfigured or disabled advisor is rejected before body parsing and writing.
Read and write errors retain their safe responses without provider or filesystem exception details.
The live adapter exposes existing callable capabilities; it is not a read-only service boundary or a security sandbox.
Original-source fingerprints preserve the snapshot and both handlers after reversal of explicit interface changes.
Shared route enforcement now supports explicitly configured HTTP methods and async handlers; existing GET contracts retain their strict defaults.
Negative tests reject changed methods, sync replacements, copied bindings, detached imports, missing owners, and reverse runtime dependencies.
The dashboard runtime decreases from 2494 to 2427 lines; its enforced legacy budget decreases to 2427.
No schema, authoritative evidence, financial formula, deployment behavior, or trading permission changes.

Verification: 4890 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 35 regressions; 378 focused dashboard, architecture, and harness tests passed.
The installed application passes authenticated GET and POST checks outside the checkout with networking prohibited.
Only synthetic temporary control files are written through the canonical writer; checks preserve file permissions, mode boundaries, and live path replacement.
The wheel is built from an isolated source copy; no build artifacts are introduced into the verification checkout.
Ownership, all four extracted route-group checks, references, source surfaces, and service links passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this comparison is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-control-routes-five.json`.

Local completion is 5/5, or 100%, for this slice.
Dashboard handler extraction covers 14/17 HTTP operations, or 82.4%; this metric does not measure service decomposition.
Reviewed CLI coverage remains 73/73, or 100%; neither percentage measures the entire architecture program.
Strict whole-phase closure remains 0/8; AI-status, request-forgery token, summary handlers, internal services, and broader phases stay open.
Next: review the remaining presentation handlers and their service boundaries before extraction.
No publication, Raspberry Pi operation, production control write, or trading authorization accompanies this change.

### Twenty-third five-step P2 slice — 2026-09-26

Review conclusion: separate history handlers and their shared filled-order query without changing SQL, parameters, responses, or connection cleanup.
The five steps cover five HTTP operations, one shared reader, and required integration controls.

| Step | Boundary | Completed implementation |
|---|---|---|
| 1 | `GET /api/trades/symbols` | Concrete handler preserves time filtering and symbol discovery |
| 2 | `GET /api/trades/recent` | Concrete handler preserves parameters, ordering, display conversions, and connection cleanup |
| 3 | Filled aliases | Three concrete handlers preserve `/api/trades/filled`, `/api/orders/filled`, and `/api/fills` |
| 4 | Shared filled reader | `dashboard/history_reader.py` owns the original query, limits, pagination, and presentation calculations |
| 5 | Application integration | Five declared live dependencies, router registration, and required history ownership checks |

`dashboard/routers/history.py` owns the handlers; runtime supplies the current database, clock, timezone, error response, and fee reader.
The shared reader imports no runtime or exchange adapter; its callers import the concrete owner directly.
Original-source fingerprints preserve all six implementations after reversal of explicit interface changes.
SQL strings retain their original contents; symbol filters remain parameters rather than interpolated values.
Legacy float presentation and zero-commission estimates remain unchanged; this relocation does not approve those accounting assumptions.
Authentication, application error handling, summary accounting, and all 17 HTTP operations remain unchanged.
The 93-line router factory receives manual review because its span contains five unchanged nested handlers.
The dashboard runtime decreases from 2639 to 2494 lines; its enforced legacy budget decreases to 2494.
No schema, persistent evidence, exchange operation, financial formula, or trading authority changes.

Verification: 4855 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 39 regressions; 343 focused dashboard, architecture, and harness tests passed.
Tests cover authenticated access, mixed timestamps, exact cutoff inclusion, pagination, parameterized symbols, current fee bindings, and cleanup after query failures.
The installed application passes all five authenticated routes outside the checkout with synthetic SQLite data and networking prohibited.
Required history checks run in local and release profiles; damaged reader imports, forwarding handlers, changed methods, and copied bindings fail.
Ownership, all three extracted route-group checks, references, source surfaces, and service links passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this comparison is not signed release evidence.
The first complete profile rejected wheel-generated source copies under `build/lib`; verified copies were preserved outside the checkout.
The complete profile was repeated after correction; no architecture check was weakened or excluded.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The corrected local artifact is `.runtime/verification-local-2.20.347-history-routes-five-recheck.json`.
Final whitespace cleanup preserves the parsed runtime syntax; focused checks verify the reduced line budget separately.

Local completion is 5/5, or 100%, for this slice.
Dashboard handler extraction covers 12/17 HTTP operations, or 70.6%; this metric does not measure service decomposition.
Reviewed CLI coverage remains 73/73, or 100%; neither percentage measures the entire architecture program.
Strict whole-phase closure remains 0/8; AI, request-forgery protection, summary handlers, internal services, and broader phases stay open.
Next: review the remaining presentation handlers and their dependencies before extraction.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Twenty-second five-step P2 slice — 2026-09-26

Review conclusion: move four read-only handlers without changing their readers, authentication, response fields, or stale-data policy.
The fifth step integrates live dependencies and required architecture checks; this slice does not claim five new routes.

| Step | Boundary | Completed implementation |
|---|---|---|
| 1 | `GET /api/trading/overview` | Concrete overview handler in `dashboard/routers/trading.py`; preserve sanitized failures and HTTP 503 |
| 2 | `GET /api/account/balances` | Concrete handler preserves current cache, lock, stale fallback, and Warning header |
| 3 | `GET /api/account/open-orders` | Concrete handler preserves current reader, stale fallback, and unavailable response |
| 4 | `GET /api/market/scenarios` | Concrete handler invokes the current scenario reader without response changes |
| 5 | Application integration | Ten declared live dependencies, one router registration, and required shared structural checks |

`TradingRouteState` resolves current namespace bindings instead of retaining startup copies; it is not a security sandbox.
The router does not import runtime; runtime retains application middleware, collectors, cache ownership, and the underlying services.
The shared route analyzer replaces duplicated host-check machinery while preserving existing host contracts and negative tests.
Required `architecture_trading_routes` checks reject forwarding stubs, changed methods, copied dependencies, detached imports, and duplicate runtime routes.
AST regressions restore only dependency qualifiers and the decorator receiver before comparing original handler fingerprints.
The complete application retains all 17 HTTP operations; authentication and rate limits remain unchanged.
No financial formula, exchange request, schema, frontend asset, persistent record, or trading authority changes.
The dashboard runtime decreases from 2681 to 2639 lines; its enforced legacy budget decreases to 2639.

Verification: 4816 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 38 regressions; 304 focused dashboard, architecture, and harness tests passed.
One initial failure exposed a remaining stale-code source assertion; its corrected owner check preserves both reason-code requirements.
The installed application passes all four authenticated routes outside the checkout with synthetic dependencies and networking prohibited.
Checks preserve unauthorized rejection, live reader replacement, stale Warning headers, sanitized failures, and unavailable HTTP 503 responses.
Ownership, host and trading route checks, references, source surfaces, and service links passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this comparison is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-trading-routes-five.json`.

Local completion is 5/5, or 100%, for this slice.
Dashboard handler extraction covers 7/17 HTTP operations, or 41.2%; this metric does not measure service decomposition.
Reviewed CLI coverage remains 73/73, or 100%; neither percentage measures the entire architecture program.
Strict whole-phase closure remains 0/8; remaining handlers, internal services, and broader architecture phases stay open.
Next: review another cohesive dashboard route group and its live dependencies before extraction.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Twenty-first five-step P2 slice — 2026-09-25

Review conclusion: move one host route group while preserving live dependencies, middleware, resource cleanup, and HTTP responses.
This slice completes three endpoint extractions and two integration steps; it does not claim five new routes.

| Step | Boundary | Completed implementation |
|---|---|---|
| 1 | Live dependencies | `dashboard/host_dependencies.py` declares 29 permitted bindings and resolves their current values |
| 2 | `GET /api/health` | Concrete handler in `dashboard/routers/host.py`; preserve cache, lock, probes, and response fields |
| 3 | `GET /api/history` | Concrete handler preserves exact volume alignment, cutoff, unavailable results, and connection cleanup |
| 4 | `GET /api/update/check` | Concrete handler uses the current update reader and preserves its response |
| 5 | Application integration | Runtime registers the router once; required harness checks enforce owners, methods, and live wiring |

The router does not import runtime or copy its namespace; application composition supplies the live interface.
The interface restricts declared lookups and hides namespace values from its representation; it is not a security sandbox.
Replacement paths, cache dictionaries, locks, and readers remain visible after app construction.
Authentication, rate limiting, database error handling, and collector lifetime remain application-owned and unchanged.
AST regressions restore only dependency qualifiers and the decorator receiver before comparing original handler fingerprints.
The complete route inventory retains all 17 HTTP operations, including methods and duplicate detection.
No response schema, accounting formula, frontend asset, deployment script, or persistent record changes.
Host readers, telemetry collection, and cache ownership remain runtime debt; this slice does not complete their service extraction.
The 104-line router factory receives manual review because its span includes three unchanged nested handlers.
The dashboard runtime decreases from 2773 to 2681 lines; its enforced legacy budget decreases to 2681.

Verification: 4778 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 33 regressions; 247 focused dashboard and architecture tests plus 19 harness tests passed.
Initial test failures exposed obsolete source locations and flat route enumeration; corrected tests retain hidden-route and duplicate detection.
The installed application passes all three authenticated routes with synthetic dependencies outside the checkout and with networking prohibited.
Checks cover unauthorized access, rate limiting, live replacements, exact history values, unavailable results, and database cleanup.
Ownership, host-route enforcement, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; it does not replace signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-host-routes-five.json`.

Local completion is 5/5, or 100%, for this slice.
Dashboard handler extraction covers 3/17 HTTP operations, or 17.6%; this metric does not measure service decomposition.
Reviewed CLI coverage remains 73/73, or 100%; neither percentage measures the entire architecture program.
Strict whole-phase closure remains 0/8; remaining dashboard handlers and broader architecture phases stay open.
Next: review another cohesive dashboard route group and its live state dependencies before extraction.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Twentieth five-step P2 slice — 2026-09-25

Review conclusion: separate the experiment CLI without changing confirmation, provenance, evidence interpretation, or promotion authority.
This slice migrates one command into five concrete components; it does not run experiments or activate a candidate.

| Step | Responsibility | Concrete owner under `ladder_dragon/strategy/prediction/` |
|---|---|---|
| 1 | Arguments and explicit confirmation fields | `experiment_parser.py` |
| 2 | Clean, annotated, published release identity | `experiment_provenance.py` |
| 3 | Generation horizons and evidence queries | `experiment_evidence.py` |
| 4 | Confirmed operations and preview handlers | `experiment_actions.py` |
| 5 | Ordered dispatch, output, and exit status | `experiment_command.py` |

The stable `bin/prediction_experiment.py` launcher delegates to the concrete command owner.
The command dispatcher decreases from 251 to 37 lines; operation handlers retain their original branches and keyword arguments.
AST regressions reconstruct the original main function and compare every original helper fingerprint.
The unchanged 102-line parser receives manual review under the 80-line warning policy; its declarative argument structure remains together.
Canonical lifecycle, champion, risk, and evidence implementations retain authority; the CLI does not copy their policy.
Existing source-inspection tests and helper imports now reference concrete owners instead of the launcher.
Required local and release checks reject missing owners, forwarding stubs, detached imports, and reverse dependencies on `bin`.

Synthetic tests reject incorrect confirmations before operation resource access and preserve exact cutoff forwarding.
Activation tests preserve the HALT lock through source verification and the writer; failed provenance prevents the writer call.
Preview retains its BLOCKED output and exit code without source verification or mutation.
Report identity mismatches fail before imports or writes; help exits before store initialization.
No schema, stored evidence, fingerprint algorithm, experiment generation, or trading permission changes.
The existing invalid CAP fallback and autotune persistence defect remain separate unresolved issues.

Verification: 4745 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 66 regressions; 121 focused tests passed before the complete run.
The installed wheel passes help, empty synthetic database reporting, and rejected confirmation checks outside the checkout, with networking prohibited.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; it does not replace signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-experiment-five.json`.

Local completion is 5/5, or 100%, for this slice.
Reviewed command coverage is 73/73, or 100%, using 69 common ownership contracts and four previously recorded pilots.
This completes registered command coverage, not every command's internal decomposition or the broader P2 phase.
Dashboard extraction and internal decomposition remain; strict whole-phase closure remains 0/8.
Next: review a bounded dashboard route group with its state dependencies, route parity tests, and required ownership controls.
No publication, Raspberry Pi operation, experiment execution, or trading authorization accompanies this change.

### Nineteenth five-step P2 slice — 2026-09-25

Review conclusion: extract percentage-ladder responsibilities without changing financial formulas, market-read order, or executor dispatch.
This slice moves one command into five concrete components, not five additional commands.

| Step | Responsibility | Concrete owner under `ladder_dragon/strategy/` |
|---|---|---|
| 1 | Rounding, spacing, and raw ladder calculations | `ladder_pct_math.py` |
| 2 | Arguments and percentage validation | `ladder_pct_parser.py` |
| 3 | Public market reads and diagnostics | `ladder_pct_market.py` |
| 4 | Notional checks and child dispatch | `ladder_pct_dispatch.py` |
| 5 | Ordered orchestration and stable launcher | `ladder_pct_command.py` |

The stable launcher retains `main()` without an added exit wrapper.
Decimal context and dotenv initialization retain their original order; local checks disable dotenv loading.
AST regressions reconstruct the original functions from the extracted components and compare their complete syntax fingerprints.
The six existing float calls remain unchanged; this slice adds no financial calculation or precision conversion.
The remaining 116-line orchestrator receives manual review under the 80-line warning threshold policy.
Its local reflow closure retains current tick, spacing, and argument values; nudging and filtering preserve their original order.
Required local and release controls reject missing implementations, forwarding stubs, detached imports, reverse dependencies, and changed startup order.
Synthetic tests verify ordered reads, exact levels, side selection, empty output, strict notional rejection, and child exit propagation.

The legacy invalid `BOT_CAP_PER_ORDER` fallback remains separate debt: it skips this local notional check even with `--strict-minnotional`.
A regression characterizes that behavior; relocation does not approve the fallback or authorize trading.
The prior autotune persistence defect also remains unresolved.
This slice adds no persistent state and makes no startup acceleration claim.

Verification: 4679 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 73 regressions; 111 focused tests passed before the complete run.
The installed wheel passes help and synthetic dispatch checks outside the checkout, with networking prohibited and no real child execution.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; it does not replace signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-ladder-pct-five.json`.

Local completion is 5/5, or 100%, for this slice.
Reviewed command coverage is 72/73, or 98.6%, using 68 common ownership contracts and four previously recorded pilots.
The remaining registered command is `prediction_experiment`; dashboard work and internal decomposition also remain.
This metric does not measure the whole architecture program; strict whole-phase closure remains 0/8.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Eighteenth five-step P2 control slice — 2026-09-25

Review conclusion: enforce existing supervisor and worker entry boundaries without relocating or changing trading runtime implementations.
This slice completes five control steps for two commands; it does not claim five new implementation owners.

| Step | Boundary | Completed control |
|---|---|---|
| 1 | `bin/ai_supervisor.py` | Exact launcher, concrete supervisor functions, unique module bindings |
| 2 | `bin/autosize_universal.py` | Exact launcher and canonical worker bootstrap |
| 3 | Live worker state | Preserve `WorkerRuntimeState(vars(runtime))`; reject namespace copies and altered lifecycle imports |
| 4 | Dependency loading | Enforce lazy bootstrap imports and inert execution, worker, and supervision package initializers |
| 5 | Installed entry points | Verify isolated dispatch, exit propagation, lazy import, and live-state behavior outside the checkout |

Required local and release checks reject missing owners, forwarding stubs, changed launcher imports, unguarded calls, and same-scope entrypoint rebinding.
The binding check reuses the existing canonical source-binding analyzer instead of copying its scope rules.
Worker checks reject eager bootstrap logic, discarded return values, and copied runtime dictionaries.
Behavioral tests exercise the real bootstrap and state adapter with a fake runtime and lifecycle runner.
They prove two-way state updates, current namespace resolution on each invocation, and exception propagation.
A fresh Python process without site-packages proves that importing the worker launcher does not import runtime or lifecycle dependencies.
Supervisor dispatch checks substitute its runtime owner; they do not initialize the production supervisor.
Complete supervisor and bootstrap AST fingerprints remain unchanged from the start of this slice.
No trading workflow, financial calculation, preflight order, persistence format, or execution permission changes.
Large existing runtime modules remain design debt; these controls do not complete their internal decomposition.

Verification: 4606 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 49 regressions; 94 focused tests passed before the complete run.
The installed wheel passes fake-owner dispatch checks for both launchers, lazy worker import, and real-adapter live-state checks.
No actual supervisor, worker loop, exchange request, or production resource starts during these smoke checks.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-runtime-entry-five.json`.

Local completion is 5/5, or 100%, for this control slice.
Reviewed command coverage is 71/73, or 97.3%, using 67 common ownership contracts and four previously recorded pilots.
The remaining registered commands are `ladder_pct_runner` and `prediction_experiment`.
Dashboard work and internal decomposition also remain; this metric does not measure the whole architecture program.
Strict whole-phase closure remains 0/8; the previously recorded autotune persistence defect remains separate and unresolved.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Seventeenth five-step P2 slice — 2026-09-25

Review conclusion: separate verification command responsibilities while preserving interpreter selection before verification dependency imports.
This slice migrates one command into five concrete components; it does not close the four other remaining commands.

| Step | Responsibility | Concrete owner under `ladder_dragon/` |
|---|---|---|
| 1 | Project interpreter selection and bounded re-execution | `harness_bootstrap.py` |
| 2 | Stable argument definitions and help text | `verification/harness_parser.py` |
| 3 | Profile, symbol, path, and permission normalization | `verification/harness_options.py` |
| 4 | Checkout SHA resolution and unavailable-identity fallback | `verification/harness_identity.py` |
| 5 | Check execution, report publication, and exit status | `verification/harness_command.py` |

The stable `bin/verification_harness.py` launcher retains the guarded bootstrap before its command import.
Bootstrap resides outside `verification` because importing that package first executes its initializer and model imports.
The exact source catalog assigns the root-level bootstrap to verification ownership.
Required controls preserve an inert root package initializer, standard-library-only bootstrap imports, and the reviewed checkout-root calculation.
They also reject missing implementations, detached canonical imports, reverse launcher imports, and changed startup ordering.
Existing source-inspection tests now inspect the parser and options owners; internal callers use the concrete command and bootstrap modules.
AST regressions recompose the extracted options block and account for the unchanged immutable output path.
The bootstrap docstring now names verification imports precisely; its executable function syntax remains unchanged.
Profiles, confirmation flags, timeouts, artifact formats, source identity values, and safety audit requirements remain unchanged.
This move adds no production state, runtime retention, or trading permission.

Verification: 4557 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 72 regressions; 284 focused tests passed before the complete run.
A fresh Python process without site-packages proves that re-execution occurs before any verification package import.
Tests cover missing interpreters, re-execution failure and loop rejection, identity fallback, argument normalization, and required ownership mutations.
The installed wheel passes offline help and an unknown-profile BLOCKED report check outside the checkout; stdout matches the report artifact.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-harness-five.json`.

Local completion is 5/5, or 100%, for this slice.
Reviewed command coverage is 69/73, or 94.5%, using 65 common ownership contracts and four previously recorded pilots.
The five components increase command coverage by one; they are not five additional commands.
Remaining commands are `ai_supervisor`, `autosize_universal`, `ladder_pct_runner`, and `prediction_experiment`.
Dashboard work and internal decomposition also remain; this metric does not measure the whole architecture program.
Strict whole-phase closure remains 0/8; the previously recorded autotune persistence defect remains separate and unresolved.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Sixteenth five-step P2 control slice — 2026-09-25

Review conclusion: enforce five existing operator and reporting owners without changing their executable interfaces or implementations.
This slice closes required-control gaps; it does not claim five new implementation relocations.

| Step | Stable command under `bin/` | Concrete owner under `ladder_dragon/` |
|---|---|---|
| 1 | `ai_plan_runner.py` | `supervision/plan_runner.py`: `main`, `parse_args` |
| 2 | `tools_cancel_open.py` | `execution/operator/cancel_open.py`: `main`, `parse_args` |
| 3 | `monthly_prediction_report.py` | `strategy/prediction/monthly_report_command.py`: `main`, `_load` |
| 4 | `validate_replay_sessions.py` | `verification/replay_sessions.py`: `main`, `build_parser` |
| 5 | `mainnet_validation_batch.py` | `verification/live/validation_batch.py`: `main`, `create_batch_manifest` |

Required local and release checks reject changed launcher imports, unguarded calls, forwarding stubs, missing implementations, invalid source, and reverse launcher imports.
Positive synthetic checkouts pass before each mutation group; unchanged implementation AST fingerprints provide separate parity evidence.
Fake-owner dispatch tests preserve inert imports, explicit invocation, arguments, and exit codes.
All five installed commands pass offline help and invalid-input checks outside the checkout, with network connections prohibited and dotenv disabled.
These checks do not start workers, cancel orders, create validation batches, import replay evidence, or send reports.
Existing behavior tests cover cancellation safeguards, batch bounds, report state, replay validation, and plan argument handling.
No financial calculation, persistence format, evidence identity, authority boundary, or production configuration changes.
Large existing modules remain architecture debt; owner enforcement does not complete their internal decomposition.

Verification: 4485 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 107 regressions; 180 focused tests passed before the complete run.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-operator-ownership-five.json`.

Local completion is 5/5, or 100%, for this control slice.
Reviewed command coverage is 68/73, or 93.2%, using 64 common ownership contracts and four previously recorded pilots.
Remaining commands are `ai_supervisor`, `autosize_universal`, `ladder_pct_runner`, `prediction_experiment`, and `verification_harness`.
Dashboard work and internal decomposition also remain; this command metric does not measure the whole architecture program.
Strict whole-phase closure remains 0/8; the previously recorded autotune persistence defect remains a separate unresolved issue.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Fifteenth five-step P2 control slice — 2026-09-25

Review conclusion: close ownership-enforcement gaps for five existing verification launchers without relocating or changing their implementations.
These commands already delegate to package owners; this slice adds the missing required controls and parity evidence.

| Step | Stable command under `bin/` | Concrete owner under `ladder_dragon/verification/live/` |
|---|---|---|
| 1 | `binance_testnet_smoke.py` | `testnet_smoke.py`: `main`, `run` |
| 2 | `binance_mainnet_canary.py` | `mainnet_canary.py`: `main`, `run_canary` |
| 3 | `mainnet_limit_maker_validation.py` | `mainnet_limit_maker_validation.py`: `main`, `run_validation_drill` |
| 4 | `mainnet_stop_limit_validation.py` | `mainnet_stop_limit_validation.py`: `main`, `run_validation_drill` |
| 5 | `mainnet_user_stream_drill.py` | `mainnet_user_stream_drill.py`: `main`, `run_drill` |

Required local and release checks enforce the exact launcher syntax, including each existing module description.
They reject unguarded calls, changed imports, missing owners, forwarding stubs, invalid source, and reverse imports from package owners into `bin`.
Each owner must retain concrete CLI and workflow definitions; this structural check supplements, not replaces, existing safety regressions.
Complete implementation AST fingerprints remain unchanged.
No confirmation, exposure limit, exchange request, persistence format, evidence identity, or production service changes.
Existing large verification modules remain design debt; an ownership check does not complete their internal decomposition.

Verification: 4378 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 107 regressions; 172 focused tests passed before the complete run.
Positive synthetic checkouts pass before mutations in both required profiles.
Launcher dispatch tests prove inert imports, one explicit invocation, argument preservation, and exit-code propagation with fake owners.
All five installed commands pass offline help and invalid-input checks outside the checkout, with network connections prohibited and dotenv disabled.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
The local artifact is `.runtime/verification-local-2.20.347-live-ownership-five.json`.

Local completion is 5/5, or 100%, for this control slice.
Reviewed command coverage is 63/73, or 86.3%, using 59 common ownership contracts and four previously recorded pilots.
The numerator counts five newly enforced existing commands, not five new implementation extractions.
Ten registered commands remain outside this reviewed coverage; dashboard decomposition also prevents P2 closure.
This metric does not measure the whole architecture program; strict whole-phase closure remains 0/8.
The previously recorded autotune persistence defect remains unresolved and separate from these controls.
No exchange qualification, publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Fourteenth five-step P2 slice — 2026-09-25

Review conclusion: separate the read-only Testnet soak monitor without changing sampling, safety thresholds, retry behavior, or signal state ownership.
This slice migrates one command and four supporting components; it neither launches a soak nor grants trading qualification.

| Step | Responsibility | Concrete owner under `ladder_dragon/verification/live/` |
|---|---|---|
| 1 | Sample values, protection coverage, violations, and grace transitions | `soak_policy.py` |
| 2 | Ordered exchange reads and read-only inventory access | `soak_sources.py` |
| 3 | Atomic reports, Decimal serialization, and final exit status | `soak_reports.py` |
| 4 | Argument defaults and validation | `soak_parser.py` |
| 5 | Startup, signal handling, retries, and the monitoring loop | `soak_command.py` |

The stable `bin/testnet_soak_monitor.py` launcher remains unchanged as an executable interface.
The mutable `RUN` flag and `_stop` handler remain together in the command owner; consumers do not copy the flag.
AST regressions recompose four extracted helpers and preserve the original function and constant syntax.
Source reads stay inside the original exception boundary; sample construction and grace evaluation remain outside it.
Account, open-order, and ticker reads retain their sequential order.
Manual review covers the 117-line command function, including interruption and exhausted-source status precedence.
No persistence format, retention rule, Testnet path isolation, endpoint permission, or production service changes.
Required local and release ownership checks reject missing implementations, detached imports, reverse launcher imports, and a broken stop handler.

Verification: 4271 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 64 regressions; 134 focused tests passed before the complete run.
Tests cover live signal state, read ordering, source retries, grace boundaries, invalid arguments, and preservation after atomic-report replacement failure.
The installed wheel passes offline help and one synthetic cycle with a fake client outside the checkout.
No Testnet or Mainnet request occurs during these smoke checks.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.

Local completion is 5/5, or 100%, for this slice.
Reviewed command coverage is 58/73, or 79.5%, using 54 common ownership contracts and the four previously recorded pilots.
The denominator and membership remain verified against `schemas/architecture_surfaces.json`; supporting modules do not increase the numerator.
This command metric does not measure the whole architecture program; strict whole-phase closure remains 0/8.
Remaining commands and dashboard decomposition still prevent P2 closure.
The previously recorded autotune persistence defect remains unresolved and separate from this monitor extraction.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Thirteenth five-step P2 slice — 2026-09-25

Review conclusion: separate the execution-authority source audit without changing safety contracts, diagnostics, or runtime authority paths.
This slice migrates one command and four supporting components; it does not implement P4 execution workflows.

| Step | Responsibility | Concrete owner under `ladder_dragon/verification/` |
|---|---|---|
| 1 | Canonical call and binding contracts | `authority_contracts.py` |
| 2 | Call observations, gates, loop placement, and nested scopes | `authority_calls.py` |
| 3 | Canonical imports, shadowing, and class binding provenance | `authority_bindings.py` |
| 4 | Source inspection and combined audit results | `authority_paths.py` |
| 5 | Checkout resolution, JSON output, and exit codes | `authority_command.py` |

The stable `bin/audit_execution_authority_paths.py` launcher remains one of the five mandatory safety audits.
AST fingerprints preserve all original declarations and contract assignments; only the command root offset changes.
The reference map points to the concrete contract owner, not the executable launcher.
Manual review covers the unchanged 86-line audit function and its safety-check order.
Existing mutation tests still reject incorrect cadence, gates, ordering, shadowing, rebinding, and nested decoy calls.
New local and release ownership regressions reject missing implementations, empty contracts, detached imports, and launcher logic.
These checks prove reviewed source properties, not arbitrary runtime behavior; runtime authority attestations remain unchanged.
No persistent state, execution permission, policy value, or production service changes.

Verification: 4207 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 65 regressions; 162 focused tests passed before the complete run.
The installed wheel audit produces the same report as the checkout when launched from an unrelated temporary directory.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.

Local completion is 5/5, or 100%, for this slice.
Reviewed command coverage is 57/73, or 78.1%, using 53 common ownership contracts and the four previously recorded pilots.
The denominator and membership remain verified against `schemas/architecture_surfaces.json`; supporting modules do not increase the numerator.
This command metric does not measure the whole architecture program; strict whole-phase closure remains 0/8.
Remaining commands and dashboard decomposition still prevent P2 closure.
The previously recorded autotune persistence defect remains unresolved and outside this mechanical safety-audit extraction.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Twelfth five-step P2 slice — 2026-09-25

Review conclusion: separate VWAP autotune responsibilities without changing formulas, history selection, persistence behavior, or executable arguments.
This slice migrates one command and four supporting components; it does not close P3 or authorize strategy changes.

| Step | Responsibility | Concrete owner under `ladder_dragon/strategy/` |
|---|---|---|
| 1 | Discount policy, smoothing, bounds, and map formatting | `autotune_math.py` |
| 2 | Historical average-cost replay and window results | `autotune_history.py` |
| 3 | Previous-value loading and state replacement | `autotune_state.py` |
| 4 | CLI argument definitions and defaults | `autotune_parser.py` |
| 5 | Validation, database setup, tuning orchestration, and output | `autotune_command.py` |

The stable `bin/gen_vwap_autotune.py` entry point remains available to supervisor and VWAP-updater subprocesses.
AST fingerprints preserve every original function after recomposing the extracted parser construction.
Manual review covers the 98-line orchestration function; it remains below the blocking threshold.
Existing premium and scale floating-point calculations remain unchanged; this extraction does not certify their numeric design.
The existing database migration call, connection lifetime, persistence format, and output order remain unchanged.
No new persistent record, retention policy, timer, or network capability is introduced.
Required local and release checks reject absent implementations, reverse launcher imports, and detached component imports.
Structural ownership does not replace behavioral regressions or prove arbitrary runtime bindings.

Verification: 4142 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 56 regressions; 148 focused tests passed before the complete run.
Tests preserve prior purchase cost, exclude future fills, and reject invalid configuration before database access.
The installed wheel passes offline help and exact-output checks against temporary synthetic SQLite state outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.

Unresolved preexisting defect: Decimal PnL cannot be serialized by the existing JSON state writer.
Its exception handler suppresses the failure, leaving previous state unchanged while command output can still succeed.
A synthetic regression records this behavior; no production state is inspected.
Correct serialization, diagnostic reporting, and restart behavior in a separate functional change before relying on persisted autotune history.
Architecture completion does not approve autotune for trading.

Local completion is 5/5, or 100%, for this slice.
Reviewed command coverage is 56/73, or 76.7%, of registered Python commands; this is not overall architecture completion.
The numerator combines 52 common command-ownership contracts with four pilots: statistics, backtest reports, numeric audit, and architecture audit.
The denominator comes from `python_command` entries in `schemas/architecture_surfaces.json`; both sets are checked for membership.
Supporting modules do not increase this numerator.
Strict whole-phase closure remains 0/8; an effort-weighted overall percentage remains unavailable.
Remaining commands and dashboard decomposition still prevent P2 closure.
No publication, Raspberry Pi operation, or trading authorization accompanies this change.

### Eleventh five-step P2 slice — 2026-09-25

Review conclusion: separate the daily digest into five concrete responsibilities without changing financial calculations or delivery behavior.
This slice migrates one command, not five commands; four supporting components do not inflate the command count.

| Step | Responsibility | Concrete owner under `ladder_dragon/execution/` |
|---|---|---|
| 1 | Period totals, exclusions, and summary value type | `digest_totals.py` |
| 2 | Exact FIFO replay and historical lot attribution | `digest_fifo.py` |
| 3 | Read-only report snapshot, calendar windows, and output | `digest_report.py` |
| 4 | Delivery dates, blocked alerts, and atomic state replacement | `digest_state.py` |
| 5 | CLI arguments, delivery orchestration, and exit codes | `digest_command.py` |

The stable `bin/daily_trading_digest.py` entry point contains only the launcher.
AST fingerprints preserve every original definition after recomposing the extracted final aggregation.
The FIFO loop remains 99 lines; manual review confirms unchanged financial order and exclusion behavior.
The extraction adds no database schema, persistent record type, retention rule, timer, or network capability.
Calendar cutoffs, legacy warnings, read-only SQLite access, and failed-delivery retries remain unchanged.
The mandatory ownership check rejects missing implementations, reverse launcher imports, and detached component imports in local and release profiles.
These structural checks do not prove arbitrary runtime binding or replace financial regressions.

Verification: 4086 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The slice adds 54 regressions; the initial focused set passed 201 tests before the fixture correction.
Two old mutation suites omitted new dependencies; their corrected shared fixture passed 164 focused tests.
All 54 digest regressions then passed, including positive fixture checks before mutation.
The installed wheel passed offline help and synthetic read-only dry-run checks outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.

Local completion is 5/5, or 100%, for this slice.
P2 now records fifty-five local command components; the common ownership check covers fifty-one commands and the five digest owners.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.
Remaining commands and dashboard decomposition still prevent P2 closure.
No publication, Raspberry Pi operation, production data access, or startup acceleration claim accompanies this change.

### Tenth five-command P2 slice — 2026-09-25

Review conclusion: these extractions preserve executable names, loopback startup, migration failure propagation, batch confirmation, and causal replay behavior.
No dashboard server, Mainnet batch, research job, production migration, or Raspberry Pi operation starts during verification.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/run_dashboard.py` | `dashboard/server_command.py` |
| 2 | `bin/db_migrate.py` | `persistence/migration_command.py` |
| 3 | `bin/run_mainnet_validation_batch.py` | `verification/live/batch_run_command.py` |
| 4 | `bin/replay_historical_entries.py` | `strategy/prediction/replay_command.py` |
| 5 | `bin/historical_replay_runner.py` | `strategy/prediction/replay_runner_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
AST fingerprints preserve implementation syntax after entry-guard removal, the dashboard root adjustment, and the canonical replay import.
Migration timing moves from the entry guard into a function; its return value preserves the executable exit code.
Dashboard startup still uses the deployed `FastAPI/pi-dashboard` tree; this move does not package that tree into the wheel.
The installed dashboard smoke intercepts the application and server; the migration smoke uses temporary SQLite state.
The other three installed commands pass offline help checks.
Manual review covers three replay functions above 80 lines; each remains below the 120-line blocking threshold.

Compatibility review: checkpoint implementation identity now includes the concrete replay owner alongside its stable launcher.
Old checkpoint files remain unchanged and are not reused under the new identity.
They still count toward existing storage limits; this change neither deletes them nor authorizes a replay restart.
Financial model source membership and immutable report contents are not rewritten.
Before deployment with pending work, review checkpoint capacity and the cost of a separately authorized recomputation.

Verification: 4032 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 54 regressions; 199 focused tests passed before the complete run.
Tests cover checkpoint preservation, interrupted replay parity, confirmation rejection, migration failures, and loopback server arguments.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this slice; no publication or deployment occurs.
P2 now records fifty-four local command components across the pilots and ten five-command slices.
The mandatory command-ownership check covers fifty commands in local and release profiles.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.
The dashboard entry-point move does not complete dashboard decomposition or close P2.

### Ninth five-command P2 slice — 2026-09-25

Review conclusion: these operational command extractions preserve advisory scope, generated values, archival safeguards, confirmations, and sanitized IP Guard failures.
No production archive, credential, exchange endpoint, AI provider, or Raspberry Pi is accessed during verification.
Retention tests use synthetic records and intercepted encryption; no new deletion authority or schedule is introduced.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/ai_advisor_smoke.py` | `ai/smoke_command.py` |
| 2 | `bin/gen_vwap_env.py` | `strategy/vwap_generate_command.py` |
| 3 | `bin/depth_archive_retention.py` | `strategy/depth_retention_command.py` |
| 4 | `bin/mainnet_validation_archive_retention.py` | `verification/live/archive_retention_command.py` |
| 5 | `bin/ip_guard.py` | `execution/ip_guard_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
AST fingerprints preserve original HEAD implementations after entry-guard removal; the IP Guard guard body becomes the package-owned `cli` wrapper.
The ownership check requires that wrapper alongside the concrete IP Guard implementation.
CLI regressions preserve sanitized error types, exit codes, and no-write behavior when IP consensus fails.
Existing retention regressions preserve pending sources and prohibit removal before successful encrypted publication and verification.
Manual review covers the two archival functions above 80 lines; both remain below the 120-line blocking threshold.
Verification: 3978 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 54 regressions; 153 focused tests passed before the complete run.
All five installed commands passed offline help checks outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this slice; no publication or deployment occurs.
P2 now records forty-nine local command components across the pilots and nine five-command slices.
The mandatory command-ownership check covers forty-five commands in local and release profiles.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.

### Eighth five-command P2 slice — 2026-09-25

Review conclusion: these reporting extractions preserve calculations, report formats, historical cutoffs, source failures, and diagnostic fallback behavior.
Mechanical relocation does not certify legacy reporting semantics or change trading readiness.
No production database, exchange request, Telegram delivery, or Raspberry Pi operation occurs during verification.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/pnl_24h.py` | `execution/pnl_window_command.py` |
| 2 | `bin/pnl_reporter.py` | `execution/pnl_report_command.py` |
| 3 | `bin/regime_pnl_report.py` | `strategy/regime_report_command.py` |
| 4 | `bin/production_soak_report.py` | `verification/production_soak_command.py` |
| 5 | `bin/auto_ladder_map.py` | `strategy/ladder_map_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
AST fingerprints match original HEAD implementations after entry-guard removal and the canonical trade-reader import adjustment.
The daily digest also imports this reader directly; no import-only launcher aliases remain.
The two commands with implicit `None` returns retain successful exit code zero.
Source-inspection tests now inspect concrete exception boundaries, not empty launchers.
Three relocated functions exceed the 80-line review threshold but remain below the 120-line blocking limit.
Manual review preserves their calculation, source-validation, and readiness-check sequences; further decomposition remains separate work.
Verification: 3924 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 51 regressions; 116 focused tests passed before the complete run.
Tests preserve exact synthetic totals, database bytes, strict snapshot cutoffs, canonical reader identity, and ladder fallback output.
All five installed commands passed offline help checks outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this slice; no publication or deployment occurs.
P2 now records forty-four local command components across the pilots and eight five-command slices.
The mandatory command-ownership check covers forty commands in local and release profiles.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.

### Seventh five-command P2 slice — 2026-09-25

Review conclusion: these command extractions preserve accounting confirmations, stopped-runtime checks, transaction boundaries, pagination, and simulation provenance.
No production import, schema retirement, commission repair, research run, or index maintenance occurs during verification.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/import_legacy_cost_basis.py` | `execution/cost_basis_command.py` |
| 2 | `bin/retire_legacy_accounting.py` | `execution/retirement_command.py` |
| 3 | `bin/revalue_legacy_commissions.py` | `execution/commission_command.py` |
| 4 | `bin/migrate_indexes.py` | `persistence/index_command.py` |
| 5 | `bin/backtest.py` | `strategy/backtest_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
AST fingerprints match original HEAD implementations after entry-guard removal and two canonical import adjustments.
The accounting commands share the original stopped-runtime guard; internal tests select the concrete owners.
The index launcher has no help parser; offline checks always supply a temporary synthetic database.
Index regressions preserve rows and prove idempotency for both supported schemas.
The ownership check requires concrete index definitions alongside its two-statement transaction entry point; other commands retain their existing minimum.
The cost-basis entry point receives manual review at 81 lines; unchanged syntax preserves its existing safety sequence.
Verification: 3873 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 49 regressions; 90 focused tests passed before the complete run.
All five installed commands passed isolated offline checks outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not signed release evidence.
The overall local profile remains BLOCKED by release continuity and dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this slice; no publication or deployment occurs.
P2 now records thirty-nine local command components across the pilots and seven five-command slices.
The mandatory command-ownership check covers thirty-five commands in local and release profiles.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.

### Sixth five-command P2 slice — 2026-09-25

Review conclusion: these tooling extractions preserve bounded capture, read-only diagnostics, exact historical values, subprocess arguments, and public aggregate output.
No capture key, account history, production archive, or environment file is read during verification.
Tests use synthetic inputs and intercepted transport; no real BNB capture or account probe runs.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/record_bnb_public.py` | `strategy/bnb_capture_command.py` |
| 2 | `bin/verify_bnb_fills.py` | `verification/bnb_fills_command.py` |
| 3 | `bin/prediction_history_backfill.py` | `strategy/prediction/history_command.py` |
| 4 | `bin/update_vwap_env.py` | `strategy/vwap_update_command.py` |
| 5 | `bin/generate_star_history.py` | `verification/star_history_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
Implementation AST fingerprints preserve original code except entry-guard removal and two VWAP child-path adjustments.
VWAP child paths still select the existing executable files; the entry guard maps the unchanged `None` result to exit code zero.
Star History CI invokes the stable module entry point and watches its concrete implementation path.
Internal tests import the owners; no import-only compatibility aliases are added.
The mandatory command-ownership check now covers thirty commands in local and release profiles.
Verification: 3824 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 48 regressions; existing capture, diagnostic, Star History, strategy, and deployment tests select the concrete owners.
All five installed commands passed offline help checks outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not release verification.
The overall local profile remains BLOCKED by release continuity and the dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this slice; no publication or deployment occurs.
P2 now records thirty-four local command components across the pilots and six five-command slices.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.

### Fifth five-command P2 slice — 2026-09-25

Review conclusion: administrative command relocation preserves operator authority, preview behavior, retention sequencing, scanner isolation, and source-root resolution.
No production reset, review, retention, or cleanup operation occurs during this work.
The retention and attribution tests retain their temporary-state regressions and now import the concrete owners.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/risk_ctl.py` | `risk/control_command.py` |
| 2 | `bin/review_unattributed_fills.py` | `ai/unresolved_review_command.py` |
| 3 | `bin/database_retention.py` | `persistence/retention_command.py` |
| 4 | `bin/check_technical_english.py` | `verification/english_command.py` |
| 5 | `bin/semgrep_scan.py` | `verification/semgrep_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
AST fingerprints preserve implementation syntax except entry-guard removal and the two source-root depth adjustments.
The mandatory ownership check covers twenty-five commands in local and release profiles.
Scanner policy, service arguments, source-check scope, and conservative deployment restart rules remain unchanged.
Verification: 3776 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 52 regressions for ownership, source roots, operator scope, and command behavior.
Existing retention, attribution lifecycle, and scanner-isolation regressions passed against their concrete owners.
Four installed commands passed offline help checks; the installed English launcher passed with a synthetic document adapter.
The real English check passed against checkout documents, including execution from an unrelated working directory.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not release verification.
The overall local profile remains BLOCKED by release continuity and the dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this slice; no publication or deployment occurs.
P2 now records twenty-nine local command components across the pilots and five five-command slices.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.
Whole-phase completion remains separate from this bounded command work.

### Fourth five-command P2 slice — 2026-09-25

Review conclusion: evidence command relocation preserves confirmation gates, source identities, temporal arguments, exclusive output creation, and existing command names.
This slice does not import production evidence, migrate a real policy, change cohorts, or authorize research or trading.
Tests use synthetic adapters and temporary state; installed commands run only parser checks.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/migrate_volatility_policy.py` | `strategy/volatility_migration_command.py` |
| 2 | `bin/volatility_policy.py` | `strategy/volatility_selection_command.py` |
| 3 | `bin/import_entry_veto_l2.py` | `strategy/prediction/entry_veto_import_command.py` |
| 4 | `bin/backfill_prediction_archive.py` | `strategy/prediction/archive_backfill_command.py` |
| 5 | `bin/import_v23_confirmation.py` | `strategy/prediction/confirmation_import_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
AST fingerprints preserve complete implementation syntax except removal of the executable entry guard.
Internal test imports select the new owners; executable references and service configuration remain unchanged.
The mandatory command-ownership check covers all twenty commands and rejects regressions through both local and release profiles.
Verification: 3724 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
This slice adds 55 regressions covering ownership, parser behavior, confirmation gates, provenance order, temporal arguments, and report identities.
All five installed commands passed offline parser checks outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; this is not release verification.
The overall local profile remains BLOCKED by release continuity and the dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this requested slice.
P2 now records twenty-four locally implemented command components across the pilots and four five-command slices.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.
The full program still requires complete phase exit evidence; component moves do not establish a whole-program percentage.

### Third five-command P2 slice — 2026-09-25

Review conclusion: observer command relocation preserves signal ownership, worker cleanup, parser defaults, SHADOW status, and existing executable names.
No capture service, private observer, or historical research starts during this implementation.
Tests use synthetic adapters and temporary paths; the market-scenario executable receives invalid configuration to stop before service construction.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/record_depth_archive.py` | `strategy/depth_record_command.py` |
| 2 | `bin/depth_archive_service.py` | `strategy/depth_service_command.py` |
| 3 | `bin/user_stream_shadow.py` | `execution/user_stream_command.py` |
| 4 | `bin/market_scenario_shadow.py` | `market_analysis/scenario_command.py` |
| 5 | `bin/historical_replay_planner.py` | `strategy/prediction/replay_planner_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
Original implementation syntax remains unchanged except removal of the executable entry guard.
The source contract enforces all fifteen commands through the existing local and release check.
Internal source consumers select the new owners; subprocess and systemd command names remain unchanged.
The existing conservative depth restart policy remains unchanged for a future authorized deployment.
Verification: 3669 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The third slice adds 55 regressions, including signal lifetime, worker cleanup, SHADOW status, and packaging coverage.
All five installed commands passed safe smoke checks outside the checkout without collection or network access.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no additional cycles or size violations; this is not release verification.
The overall local profile remains BLOCKED by release continuity and the dependent cycle and size checks.
Local completion for this requested slice is 5/5, or 100%; publication and Raspberry Pi deployment remain outside scope.
Installed-package review found that wheels omit the runtime `product_version` module, although checkout execution resolves it.
The packaging correction explicitly includes that module; a configuration regression and repeated installed execution verify the correction.
Whole-phase closure remains 0/8; these components do not complete dashboard extraction or the broader P2 acceptance criteria.
Strict whole-phase completion is 0%; an effort-weighted overall percentage cannot be derived from the current unweighted plan.
P2 now records nineteen locally implemented command components across the pilots and three five-command slices.

### Second five-command P2 slice — 2026-09-25

Review conclusion: these command implementations can move without changes to parser behavior, evidence policy, maintenance semantics, or deployment names.
The maintenance command retains its explicit path and operator behavior; tests use temporary synthetic state only.
Replay commands retain the canonical acceptance policy and exact fee parsing.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/audit_legacy_compatibility.py` | `execution/compatibility_command.py` |
| 2 | `bin/audit_user_stream_soak.py` | `execution/user_stream_soak_command.py` |
| 3 | `bin/calibrate_replay.py` | `verification/calibration_command.py` |
| 4 | `bin/validate_replay_outcomes.py` | `verification/replay_outcomes_command.py` |
| 5 | `bin/maintenance_state.py` | `execution/maintenance_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
Implementation AST fingerprints preserve the complete original code except the executable entry guard.
The required command-ownership check now covers ten commands and rejects regressions through both local and release profiles.
Existing command names, service references, and depth restart policy remain unchanged.
Verification: 3614 tests passed and two skipped; compilation, five safety audits, secret scanning, and Semgrep passed.
The second slice adds 57 regressions, including real maintenance round trips and replay producer-to-consumer rejection with synthetic evidence.
All five installed commands passed offline parser smoke checks outside the checkout.
Ownership, references, source surfaces, and service-link checks passed.
Diagnostic comparison against HEAD found no new cycles or size violations; it is not release verification.
The overall local profile remains BLOCKED by release continuity and the dependent cycle and size checks.
Local implementation completion is 5/5, or 100%, for this second slice; publication and deployment are not performed.
The overall progress denominator remains eight phases; these five components do not close P2 or other phases.
Strict whole-phase closure remains 0/8, or 0%; an effort-weighted overall percentage remains unavailable.
P2 now records fourteen locally implemented command components; this count is not a percentage of the whole architecture program.

### Five-command P2 slice — 2026-09-25

Review conclusion: these five command components can move without changes to financial policy, execution authority, or deployment interfaces.
Existing uncommitted updater and protection fixes remain separate from the mechanical extraction evidence.

| Step | Stable command | Concrete package owner |
|---|---|---|
| 1 | `bin/audit_semantic_authorities.py` | `verification/semantic_authorities.py` |
| 2 | `bin/audit_exchange_boundaries.py` | `verification/exchange_boundaries.py` |
| 3 | `bin/audit_guard_contracts.py` | `verification/guard_contracts.py` |
| 4 | `bin/audit_ai_readiness.py` | `verification/ai_readiness_command.py` |
| 5 | `bin/audit_replay_readiness.py` | `verification/replay_readiness_command.py` |

Package-owner paths are relative to `ladder_dragon/`.
All five launchers retain nine lines; implementation syntax matches the pre-extraction HEAD after checkout-root adjustment and entry-guard removal.
Internal test consumers and source-policy references select the concrete owners.
The required `architecture_command_ownership` check runs in local and release profiles.
Mutation tests reject launcher logic, forwarding implementations, reverse imports, and missing owners through both profiles.
The five existing safety audits retain their interfaces and comprehensive scope.
Depth restart policy remains unchanged; unknown paths still require a restart during a separately authorized deployment.
Verification: 3557 tests passed and two skipped; compilation, all five safety audits, secret scanning, and Semgrep passed.
All five commands passed installed-package smoke checks from outside the checkout; 54 extraction regressions passed.
Command ownership, source ownership, references, surfaces, and service-link checks passed.
The overall local profile remains BLOCKED by release continuity and its dependent architecture checks until the candidate is signed.
This is local implementation evidence, not a release or deployment PASS.

#### Progress denominator

This requested slice contains five component steps, not five complete architecture phases.
Local implementation completion is 5/5, or 100%, for this requested slice; release verification remains pending.
The full program contains eight phases, P0 through P7; zero phases currently have complete exit evidence.
Strict phase closure is 0/8, or 0%; this metric does not count partial implementation as zero work.
An effort-weighted overall percentage is unavailable because remaining work has no reviewed weighted task inventory.
Do not present a component count as the percentage of total architecture work completed.

### Release-candidate growth correction — 2026-09-16

The release profile rejects eight growth violations in seven files against the signed v2.20.340 baseline.
The bounded correction covers these concrete owners:

- `BinanceTransport._signed_response` owns complete response reads; request signing and retry decisions remain in the transport coordinator.
- `execution/journal/metadata.py` owns the existing metadata transaction and rejects direct settlement replacement.
- `execution/protection/empty_entry.py` owns terminal zero-fill recording without creating protection.
- `execution/protection/lot_lookup.py` resolves the current worker connection and callbacks at each invocation.
- `execution/protection/buy_inventory.py` owns the exact partial-exit read and residual calculation.
- `risk/limit_values.py` owns exact conversion and the effective-limit status allowlist.
- `prediction/historical_values.py` owns finite selection values; the replay module retains its source-hash helper and original source membership.

Four relocated functions retain identical executable AST, excluding documentation indentation.
No schema, historical artifact, model identifier, execution permission, or financial policy changes during these moves.
The full test harness checks owner identity, resource replacement, exact arithmetic, and fail-closed response limits.
Reduced module budgets and the existing lineage-based gate prevent reintroduction of the observed growth.
Release completion remains conditional on the full signed-candidate profile; file movement does not establish a startup speed improvement.

### Earlier implementation record

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
| P2 | Commands: 73/73 (100%); extracted dashboard operations: 14/17 (82.4%) | Local candidate | Syntax parity, authenticated routes, live bindings, harness rejection | Remaining dashboard handlers, service ownership, and internal decomposition pending |
| P3 | Pending | Not implemented | None | Not inventoried |
| P4 | Pending | Not implemented | None | Not inventoried |
| P5 | Pending | Not implemented | None | Not inventoried |
| P6 | Pending | Not implemented | None | Not inventoried |
| P7 | Pending | Not implemented | None | Not inventoried |

Related current contracts: [Architecture](ARCHITECTURE.md), [Domain authorities](DOMAIN_AUTHORITIES.md), and [Local artifacts](LOCAL_ARTIFACTS.md).
