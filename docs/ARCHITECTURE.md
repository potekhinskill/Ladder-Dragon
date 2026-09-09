# Ladder Dragon architecture

Ladder Dragon uses a package-first structure.
Reusable application and domain logic is in `ladder_dragon/`.
Files in `bin/` are stable command-line entry points.
The `deploy/`, `FRONT/`, and `tests/` directories have separate technical scopes.

See the [Architecture evolution plan](ARCHITECTURE_EVOLUTION_PLAN.md) for proposed ownership changes, migration phases, and permanent harness controls.
The first ownership slice is implemented; the remaining target structure is still proposed.

## Source ownership gate

`schemas/architecture_contract.json` assigns Python files to exact directory owners or explicit file owners.
Ownership does not propagate into an unregistered subdirectory.
The required `architecture_ownership` check runs in local and release harness profiles.
Run `.venv/bin/python -m bin.audit_architecture` for its source-only inventory.

The check includes tracked and nonignored new Python files outside tests.
It rejects unknown owners and static application imports from `bin`, including nested imports.
Invalid contracts, source symlinks, parse failures, or unavailable Git input return BLOCKED.
Reports identify HEAD, the contract hash, and observed source hashes; working changes are not described as an immutable release.
Static imports and size metrics are inventoried without importing the application.
Function observations include lexical names, definition and decorator-inclusive span lines, async status, and duplicate-name ambiguity.
The maximum function size now includes decorators; duplicate definitions remain separate and cannot establish a unique runtime identity.
These measurements do not approve size budgets; the existing report ceiling and fail-closed input checks remain unchanged.
The required `architecture_new_sizes` profile check applies approved limits to new production paths and lexical function names against verified release lineage.
New modules above 500 lines and new functions above 120 fail; functions above 80 through 120 produce review warnings.
Changed ambiguous name groups block classification; unchanged groups remain legacy observations, not approved allowances.
Existing growth and test-file size limits remain outside this scoped check; existing safety and size checks remain mandatory.
The separate required `architecture_legacy_sizes` check rejects existing modules above the larger of 500 lines and their predecessor size.
Existing functions cannot exceed the larger of 120 lines and their predecessor span; changed ambiguous groups block comparison.
Historical module sizes include trailing comments and blank lines. Shrinkage reduces the next release's ceiling, down to the standard limit.
Non-growth does not approve legacy design or replace explicit exception review; test-file size enforcement remains pending.
Dynamic import calls now have bounded syntactic observations, including explicit import aliases and literal relative targets.
Only inventoried local targets are named; other expressions receive syntax hashes and unresolved or external classifications.
Static imports now map to inventoried module files and package initializers, with conservative cycle groups reported separately.
The graph separates direct candidate imports from parent initializer dependencies and reports cyclic groups in both views.
Each combined group includes its direct subgroups and internal edge counts without counting overlapping edge kinds twice.
Local import sites now report deferred, conditional, class-body, and candidate type-guard context flags without printing guard expressions.
The unguarded direct-cycle view excludes deferred and conditional sites, but does not prove runtime startup reachability.
All observed imports remain in the complete conservative graph, including rebound type-guard names.
Ambiguous module identities block analysis; missing external targets and imported attributes do not become invented source nodes.
Runtime binding, cycle budgets, capabilities, and additional size budgets remain outside this check.
Existing financial safety audits remain mandatory.

The required `architecture_cycles` profile check prohibits new direct cyclic edges relative to the previous release selected by `release_continuity`.
This comparison includes deferred and conditional imports; shrinking a cycle is allowed, but restoring removed cyclic edges is not.
The check reads bounded immutable Git objects without importing historical code or accepting a candidate-provided graph budget.
Missing lineage, missing history, invalid source, or incomplete current analysis returns BLOCKED.
The inventory command remains diagnostic; local and release profiles additionally run the cycle-growth gate.
The same gate separately rejects growth in the combined graph, including package initializer dependencies.
Existing combined cycles never authorize new direct cycles; both comparisons use the same immutable release source.
The verification package exports result models only; import `HarnessRunner` from `ladder_dragon.verification.runner` when orchestration is required.
These conservative source restrictions do not prove import failure or startup execution. Dynamic cycle enforcement remains pending.

The bounded report is derived verification evidence, not trading state.
It uses the existing release artifact workflow and creates no Pi service or database.

## Dependency direction

```text
bin / FastAPI routes
        ↓
application services (supervision, verification)
        ↓
domain services (strategy, risk, AI policies)
        ↓
infrastructure adapters (execution, SQLite, Binance)
```

Package code must never import `bin`. Operator commands import only their
package `main` function, and ASGI launchers expose only the packaged `app`.
Tests and extensions import the owning package directly.

## Current packages

| Package | Responsibility |
|---|---|
| `ladder_dragon/supervision/` | Supervisor configuration, worker orchestration, adaptive entry and VWAP policies |
| `ladder_dragon/strategy/` | Replay, prediction, simulation, regimes and expectancy |
| `ladder_dragon/risk/` | Limits, portfolio state and risk statistics |
| `ladder_dragon/risk/trade_streaks.py` | Bounded FIFO state and SELL outcomes for loss-streak gates |
| `ladder_dragon/execution/` | Binance adapters, orders, protection, recovery, accounting and streams |
| `ladder_dragon/ai/` | Advisory context, policy, knowledge and evidence |
| `ladder_dragon/dashboard/` | FastAPI routes, repositories, services and host telemetry |
| `ladder_dragon/persistence/` | Versioned SQLite migrations and storage infrastructure |
| `ladder_dragon/persistence/retention.py` | Backup-gated archive and retention for terminal derived telemetry |
| `ladder_dragon/verification/` | Release, Testnet and Raspberry verification profiles |

Prediction research is in `ladder_dragon/strategy/prediction/`.
Scenario calculations are in `ladder_dragon/strategy/scenario_analysis.py`.
Public collection is in `ladder_dragon/market_analysis/`.
This package has no order or credential dependency.
Each module has one responsibility:

- `decision_value` owns the monetary target;
- `historical_dataset` and `advanced_features` own cutoff-safe evidence;
- `statistical_models` owns transparent challengers;
- `challengers` owns full-coverage comparisons for live predictor evidence;
- `ensemble` owns the defensive policy;
- `experiments` owns same-snapshot SHADOW variants;
- `approval` owns confidence interval and Holm gates;
- `walk_forward` owns chronological evaluation;
- `monthly_contour` owns recurring artifacts.

Historical splits share immutable training-prefix storage and use binary label cutoffs.
Each HMM sequence contains one symbol and one prediction horizon.
The ensemble treats `FLAT` and `UP` as one safe family.
Confident `DOWN` or `PANIC` results stop a BUY.
Weak danger evidence can only reduce CAP.
These modules cannot import exchange order capabilities.

## Monolith register

CLI and ASGI paths are launchers, not import aliases. The following package
runtimes remain incremental coordinators and are covered by strict
non-growth budgets:

| File | Main remaining seams |
|---|---|
| `ladder_dragon/supervision/runtime.py` | per-symbol planning, runtime bootstrap and the main supervision loop |
| `ladder_dragon/supervision/shadow_collection.py` | validation and scheduling for read-only prediction symbols |
| `ladder_dragon/execution/worker/bootstrap.py` | thin executable bootstrap |
| `ladder_dragon/execution/worker/lifecycle.py` | worker preflight, initial plan, resource startup and cleanup |
| `ladder_dragon/execution/worker/event_loop.py` | fill reconciliation, protection, PANIC, gap and time-stop loop |
| `ladder_dragon/execution/worker/runtime.py` | shared exchange adapters and late-bound execution dependencies |
| `ladder_dragon/dashboard/runtime.py` | dashboard coordinator pending router/service extraction |
| `ladder_dragon/execution/order_recovery.py` | journal schema, lifecycle commands, query projections |
| `ladder_dragon/strategy/prediction/runtime.py` | feature/outcome journal coordinator pending final store extraction |
| `ladder_dragon/ai/context/runtime.py` | decision repository, attribution, RAG evidence and serialization |
| `ladder_dragon/execution/orders/runtime.py` | LIMIT, MARKET, OCO and OTOCO orchestration |
| `ladder_dragon/execution/protection/runtime.py` | protection verification, residual protection and emergency flatten |

Future work must extract one cohesive seam at a time and migrate production
and test imports to the owning package in the same change. A move is complete
only when:

1. executable CLI paths remain compatible and no import-only facade remains;
2. the package has no reverse dependency on `bin`;
3. focused and full regression suites pass;
4. the old monolith becomes smaller;
5. the architecture budget is reduced to the new line count.

This avoids a flag-day rewrite of the LIVE execution path while making every
release structurally better than its predecessor.

The supervisor risk snapshot, recovery gate, and child shutdown have separate modules.
These modules are `risk_cycle.py`, `recovery_gate.py`, and `process_manager.py`.
The supervisor runtime injects exchange and persistence adapters explicitly.
This design preserves fail-closed behavior without a reverse dependency.
Authentication/transient preflight classification, bounded retry schedules and
heartbeat-aware waits are owned by `preflight_resilience.py`; the runtime
retains only orchestration and explicit callbacks for status and clocks.

The worker CLI constructs a `WorkerRuntimeState` over the live execution
runtime namespace. `lifecycle.py` owns preflight, initial planning and resource
cleanup, while `event_loop.py` observes signal-driven `RUN` changes and current
SQLite/WebSocket objects instead of stale snapshots. The event loop can
reconcile fills, maintain protection and perform fail-closed exits, but it
cannot create new BUY exposure. Cleanup attempts every observer, transport and
symbol-lock release even when an earlier cleanup callback fails.
Order planning exposes only Decimal prices, quantities, notionals, and rounding callbacks.
No binary-float planning compatibility API remains.

## Runtime entry points

`bin/stats_view.py` now delegates to `ladder_dragon/execution/stats_view.py`.
The package owns its concrete parser and report functions, without importing the former launcher.
The command retains its arguments, exit behavior, and read-only SQLite adapter.

`bin/audit_backtest_reports.py` delegates to `ladder_dragon/verification/backtest_reports.py`.
The package owns classification, input discovery, and the command parser.
Its tests import the implementation owner, not the executable launcher.

`bin/audit_numeric_boundaries.py` delegates to `ladder_dragon/verification/numeric_boundaries.py`.
The package owns the unchanged numeric budgets and analyzer; the harness retains its original executable command.

See [Architecture state and policy map](ARCHITECTURE_STATE_MAP.md) for reviewed store anchors and existing policy sources.
See [Command and deployment source map](ARCHITECTURE_SURFACE_MAP.md) for registered commands, service templates, frontend assets, and migrations.

`bin/ai_supervisor.py`, `bin/autosize_universal.py`, both Binance verification
commands and the safeguarded cancellation command expose only executable
launchers. `FastAPI/pi-dashboard/app.py` exposes only the packaged ASGI app.
They do not emulate package modules or support historical extension imports.

See [Command and service reference](COMMAND_REFERENCE.md) for all executable entry points.
See [Implementation status](IMPLEMENTATION_STATUS.md) for current runtime gates.

Private local state follows [LOCAL_ARTIFACTS.md](LOCAL_ARTIFACTS.md). Architecture
work never moves or deletes runtime databases, `.runtime`, caches or environment
backups automatically.
