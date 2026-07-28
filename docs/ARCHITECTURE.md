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

Package code must never import `bin`. Compatibility commands may import package
code and re-export established symbols, allowing systemd, operator commands and
third-party imports to remain stable while implementations move.

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

Historical CLI and ASGI paths are thin compatibility facades. The following
package runtimes remain incremental coordinators and are covered by strict
non-growth budgets:

| File | Main remaining seams |
|---|---|
| `ladder_dragon/supervision/runtime.py` | per-symbol planning, runtime bootstrap and the main supervision loop |
| `ladder_dragon/execution/worker/runtime.py` | worker runtime coordinator pending further service extraction |
| `ladder_dragon/dashboard/runtime.py` | dashboard coordinator pending router/service extraction |
| `ladder_dragon/execution/order_recovery.py` | journal schema, lifecycle commands, query projections |
| `ladder_dragon/strategy/prediction/runtime.py` | compatibility coordinator for modular prediction APIs |

Future work must extract one cohesive seam at a time behind an unchanged
facade. A move is complete only when:

1. callers and CLI paths remain compatible;
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

## Compatibility facades

`bin/ai_supervisor.py`, `bin/autosize_universal.py`, both Binance verification
commands, the safeguarded cancellation command and
`FastAPI/pi-dashboard/app.py` contain no business logic. They delegate to
package modules so existing systemd, operator and third-party entry points do
not change during decomposition.

Private local state follows [LOCAL_ARTIFACTS.md](LOCAL_ARTIFACTS.md). Architecture
work never moves or deletes runtime databases, `.runtime`, caches or environment
backups automatically.
