# Ladder Dragon architecture

Ladder Dragon uses a package-first structure: reusable application and domain
logic lives under `ladder_dragon/`; files under `bin/` are stable command-line
entry points; `deploy/` owns host integration; `FRONT/` contains published
static assets; and `tests/` mirrors the technical boundaries.

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
| `ladder_dragon/execution/` | Binance adapters, orders, protection, recovery, accounting and streams |
| `ladder_dragon/ai/` | Advisory context, policy, knowledge and evidence |
| `ladder_dragon/persistence/` | Versioned SQLite migrations and storage infrastructure |
| `ladder_dragon/verification/` | Release, Testnet and Raspberry verification profiles |

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
| `ladder_dragon/strategy/prediction/runtime.py` | compatibility coordinator for modular prediction APIs |

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

The supervisor's authoritative risk snapshot, startup recovery gate and child
shutdown lifecycle are now physically owned by `risk_cycle.py`,
`recovery_gate.py` and `process_manager.py`. The compatibility runtime injects
its exchange and persistence adapters explicitly, preserving fail-closed
behavior and test isolation without introducing a reverse dependency.
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

Private local state follows [LOCAL_ARTIFACTS.md](LOCAL_ARTIFACTS.md). Architecture
work never moves or deletes runtime databases, `.runtime`, caches or environment
backups automatically.
