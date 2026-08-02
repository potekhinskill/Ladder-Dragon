# Ladder Dragon architecture

Ladder Dragon uses a package-first structure.
Reusable application and domain logic is in `ladder_dragon/`.
Files in `bin/` are stable command-line entry points.
The `deploy/`, `FRONT/`, and `tests/` directories have separate technical scopes.

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

## Runtime entry points

`bin/ai_supervisor.py`, `bin/autosize_universal.py`, both Binance verification
commands and the safeguarded cancellation command expose only executable
launchers. `FastAPI/pi-dashboard/app.py` exposes only the packaged ASGI app.
They do not emulate package modules or support historical extension imports.

See [Command and service reference](COMMAND_REFERENCE.md) for all executable entry points.
See [Implementation status](IMPLEMENTATION_STATUS.md) for current runtime gates.

Private local state follows [LOCAL_ARTIFACTS.md](LOCAL_ARTIFACTS.md). Architecture
work never moves or deletes runtime databases, `.runtime`, caches or environment
backups automatically.
